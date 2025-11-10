"""
Database Service for Underwriting AI System
Manages PostgreSQL connections and provides CRUD operations for rule containers, banks, and policies.
"""

import os
import logging
from datetime import datetime
from typing import Optional, List, Dict, Any
from contextlib import contextmanager

from sqlalchemy import create_engine, Column, Integer, String, Boolean, DateTime, Text, ForeignKey, CheckConstraint, Index, text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship, Session
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.sql import func

logger = logging.getLogger(__name__)

Base = declarative_base()


# SQLAlchemy Models
class Bank(Base):
    __tablename__ = 'banks'

    bank_id = Column(String(50), primary_key=True)
    bank_name = Column(String(255), nullable=False)
    description = Column(Text)
    contact_email = Column(String(255))
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    containers = relationship("RuleContainer", back_populates="bank", cascade="all, delete-orphan")
    requests = relationship("RuleRequest", back_populates="bank")


class PolicyType(Base):
    __tablename__ = 'policy_types'

    policy_type_id = Column(String(50), primary_key=True)
    policy_name = Column(String(255), nullable=False)
    description = Column(Text)
    category = Column(String(50))
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    containers = relationship("RuleContainer", back_populates="policy_type", cascade="all, delete-orphan")
    requests = relationship("RuleRequest", back_populates="policy_type")


class RuleContainer(Base):
    __tablename__ = 'rule_containers'

    id = Column(Integer, primary_key=True)
    container_id = Column(String(255), unique=True, nullable=False)
    bank_id = Column(String(50), ForeignKey('banks.bank_id', ondelete='CASCADE'), nullable=False)
    policy_type_id = Column(String(50), ForeignKey('policy_types.policy_type_id', ondelete='CASCADE'), nullable=False)

    # Container details
    platform = Column(String(20), nullable=False)
    container_name = Column(String(255))
    endpoint = Column(String(500), nullable=False)
    port = Column(Integer)

    # Status tracking
    status = Column(String(20), default='deploying')
    health_check_url = Column(String(500))
    last_health_check = Column(DateTime)
    health_status = Column(String(20), default='unknown')
    failure_reason = Column(Text)

    # Deployment metadata
    document_hash = Column(String(64))
    s3_policy_url = Column(String(500))
    s3_jar_url = Column(String(500))
    s3_drl_url = Column(String(500))
    s3_excel_url = Column(String(500))

    # Versioning
    version = Column(Integer, default=1)
    is_active = Column(Boolean, default=True)

    # Resource usage
    cpu_limit = Column(String(20))
    memory_limit = Column(String(20))

    # Timestamps
    deployed_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    stopped_at = Column(DateTime)

    # Relationships
    bank = relationship("Bank", back_populates="containers")
    policy_type = relationship("PolicyType", back_populates="containers")
    requests = relationship("RuleRequest", back_populates="container")
    deployment_history = relationship("ContainerDeploymentHistory", back_populates="container", cascade="all, delete-orphan")

    # Constraints
    __table_args__ = (
        CheckConstraint("platform IN ('docker', 'kubernetes', 'local')", name='check_platform'),
        CheckConstraint("status IN ('deploying', 'running', 'stopped', 'failed', 'unhealthy')", name='check_status'),
        CheckConstraint("health_status IN ('healthy', 'unhealthy', 'unknown')", name='check_health_status'),
        Index('idx_containers_bank_policy', 'bank_id', 'policy_type_id'),
        Index('idx_containers_status', 'status'),
        Index('idx_containers_health', 'health_status'),
        Index('idx_containers_platform', 'platform'),
    )


class RuleRequest(Base):
    __tablename__ = 'rule_requests'

    id = Column(Integer, primary_key=True)
    container_id = Column(Integer, ForeignKey('rule_containers.id', ondelete='SET NULL'))
    bank_id = Column(String(50), ForeignKey('banks.bank_id', ondelete='SET NULL'))
    policy_type_id = Column(String(50), ForeignKey('policy_types.policy_type_id', ondelete='SET NULL'))

    # Request details
    request_id = Column(UUID(as_uuid=True), server_default=func.uuid_generate_v4())
    endpoint = Column(String(255))
    http_method = Column(String(10))

    # Payload
    request_payload = Column(JSONB)
    response_payload = Column(JSONB)

    # Performance
    execution_time_ms = Column(Integer)
    status_code = Column(Integer)
    status = Column(String(20))
    error_message = Column(Text)

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    container = relationship("RuleContainer", back_populates="requests")
    bank = relationship("Bank", back_populates="requests")
    policy_type = relationship("PolicyType", back_populates="requests")

    __table_args__ = (
        CheckConstraint("status IN ('success', 'error', 'timeout')", name='check_request_status'),
        Index('idx_requests_container', 'container_id'),
        Index('idx_requests_bank', 'bank_id'),
        Index('idx_requests_created_at', 'created_at'),
        Index('idx_requests_status', 'status'),
    )


class ContainerDeploymentHistory(Base):
    __tablename__ = 'container_deployment_history'

    id = Column(Integer, primary_key=True)
    container_id = Column(Integer, ForeignKey('rule_containers.id', ondelete='CASCADE'))
    bank_id = Column(String(50))
    policy_type_id = Column(String(50))

    # Deployment details
    action = Column(String(20))
    version = Column(Integer)
    platform = Column(String(20))
    endpoint = Column(String(500))

    # Change tracking
    document_hash = Column(String(64))
    changes_description = Column(Text)
    deployed_by = Column(String(100))

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    container = relationship("RuleContainer", back_populates="deployment_history")

    __table_args__ = (
        CheckConstraint("action IN ('deployed', 'updated', 'stopped', 'restarted', 'failed')", name='check_action'),
        Index('idx_history_container', 'container_id'),
        Index('idx_history_created_at', 'created_at'),
    )


class ExtractedRule(Base):
    __tablename__ = 'extracted_rules'

    id = Column(Integer, primary_key=True)
    bank_id = Column(String(50), ForeignKey('banks.bank_id', ondelete='CASCADE'), nullable=False)
    policy_type_id = Column(String(50), ForeignKey('policy_types.policy_type_id', ondelete='CASCADE'), nullable=False)

    # Rule details
    rule_name = Column(String(255), nullable=False)
    requirement = Column(Text, nullable=False)
    category = Column(String(100))
    source_document = Column(String(500))

    # Metadata
    document_hash = Column(String(64))
    extraction_timestamp = Column(DateTime, default=datetime.utcnow)
    is_active = Column(Boolean, default=True)

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    bank = relationship("Bank")
    policy_type = relationship("PolicyType")

    __table_args__ = (
        Index('idx_extracted_rules_bank_policy', 'bank_id', 'policy_type_id'),
        Index('idx_extracted_rules_active', 'is_active'),
        Index('idx_extracted_rules_created_at', 'created_at'),
    )


class DatabaseService:
    """Service class for database operations"""

    def __init__(self, database_url: Optional[str] = None):
        """
        Initialize database connection.

        Args:
            database_url: PostgreSQL connection string. If None, uses DATABASE_URL env var.
        """
        self.database_url = database_url or os.getenv(
            'DATABASE_URL',
            'postgresql://underwriting_user:underwriting_pass@localhost:5432/underwriting_db'
        )

        self.engine = create_engine(self.database_url, pool_pre_ping=True, echo=False)
        self.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=self.engine)

        logger.info(f"Database service initialized with URL: {self.database_url.split('@')[1] if '@' in self.database_url else 'localhost'}")

    @contextmanager
    def get_session(self) -> Session:
        """Context manager for database sessions"""
        session = self.SessionLocal()
        try:
            yield session
            session.commit()
        except Exception as e:
            session.rollback()
            logger.error(f"Database session error: {e}")
            raise
        finally:
            session.close()

    # Bank operations
    def create_bank(self, bank_id: str, bank_name: str, description: str = None, contact_email: str = None) -> Bank:
        """Create or update a bank"""
        with self.get_session() as session:
            bank = session.query(Bank).filter_by(bank_id=bank_id).first()
            if bank:
                bank.bank_name = bank_name
                bank.description = description
                bank.contact_email = contact_email
                bank.updated_at = datetime.utcnow()
            else:
                bank = Bank(
                    bank_id=bank_id,
                    bank_name=bank_name,
                    description=description,
                    contact_email=contact_email
                )
                session.add(bank)
            session.commit()
            session.refresh(bank)
            return bank

    def get_bank(self, bank_id: str) -> Optional[Dict[str, Any]]:
        """Get a bank by ID as dictionary"""
        with self.get_session() as session:
            bank = session.query(Bank).filter_by(bank_id=bank_id).first()
            if not bank:
                return None

            # Convert to dictionary within session context
            return {
                'bank_id': bank.bank_id,
                'bank_name': bank.bank_name,
                'description': bank.description,
                'contact_email': bank.contact_email,
                'is_active': bank.is_active,
                'created_at': bank.created_at.isoformat() if bank.created_at else None,
                'updated_at': bank.updated_at.isoformat() if bank.updated_at else None
            }

    def list_banks(self, active_only: bool = True) -> List[Dict[str, Any]]:
        """List all banks as dictionaries"""
        with self.get_session() as session:
            query = session.query(Bank)
            if active_only:
                query = query.filter_by(is_active=True)
            banks = query.all()

            # Convert to dictionaries within session context
            return [{
                'bank_id': bank.bank_id,
                'bank_name': bank.bank_name,
                'description': bank.description,
                'contact_email': bank.contact_email,
                'is_active': bank.is_active,
                'created_at': bank.created_at.isoformat() if bank.created_at else None,
                'updated_at': bank.updated_at.isoformat() if bank.updated_at else None
            } for bank in banks]

    # Policy Type operations
    def create_policy_type(self, policy_type_id: str, policy_name: str, description: str = None, category: str = None) -> PolicyType:
        """Create or update a policy type"""
        with self.get_session() as session:
            policy_type = session.query(PolicyType).filter_by(policy_type_id=policy_type_id).first()
            if policy_type:
                policy_type.policy_name = policy_name
                policy_type.description = description
                policy_type.category = category
                policy_type.updated_at = datetime.utcnow()
            else:
                policy_type = PolicyType(
                    policy_type_id=policy_type_id,
                    policy_name=policy_name,
                    description=description,
                    category=category
                )
                session.add(policy_type)
            session.commit()
            session.refresh(policy_type)
            return policy_type

    def get_policy_type(self, policy_type_id: str) -> Optional[Dict[str, Any]]:
        """Get a policy type by ID as dictionary"""
        with self.get_session() as session:
            pt = session.query(PolicyType).filter_by(policy_type_id=policy_type_id).first()
            if not pt:
                return None

            # Convert to dictionary within session context
            return {
                'policy_type_id': pt.policy_type_id,
                'policy_name': pt.policy_name,
                'description': pt.description,
                'category': pt.category,
                'is_active': pt.is_active,
                'created_at': pt.created_at.isoformat() if pt.created_at else None,
                'updated_at': pt.updated_at.isoformat() if pt.updated_at else None
            }

    def list_policy_types(self, active_only: bool = True, category: str = None) -> List[Dict[str, Any]]:
        """List all policy types as dictionaries"""
        with self.get_session() as session:
            query = session.query(PolicyType)
            if active_only:
                query = query.filter_by(is_active=True)
            if category:
                query = query.filter_by(category=category)
            policy_types = query.all()

            # Convert to dictionaries within session context
            return [{
                'policy_type_id': pt.policy_type_id,
                'policy_name': pt.policy_name,
                'description': pt.description,
                'category': pt.category,
                'is_active': pt.is_active,
                'created_at': pt.created_at.isoformat() if pt.created_at else None,
                'updated_at': pt.updated_at.isoformat() if pt.updated_at else None
            } for pt in policy_types]

    # Container operations
    def register_container(self, container_data: Dict[str, Any]) -> RuleContainer:
        """Register a new rule container"""
        with self.get_session() as session:
            # Ensure bank and policy type exist
            bank_id = container_data.get('bank_id')
            policy_type_id = container_data.get('policy_type_id')

            # Deactivate old containers for this bank+policy combination
            old_containers = session.query(RuleContainer).filter_by(
                bank_id=bank_id,
                policy_type_id=policy_type_id,
                is_active=True
            ).all()

            for old_container in old_containers:
                old_container.is_active = False
                old_container.status = 'stopped'
                old_container.stopped_at = datetime.utcnow()

            # Create new container
            container = RuleContainer(**container_data)
            session.add(container)
            session.commit()
            session.refresh(container)

            logger.info(f"Registered container {container.container_id} for {bank_id}/{policy_type_id}")
            return container

    def _container_to_dict(self, container: RuleContainer) -> Dict[str, Any]:
        """Convert RuleContainer object to dictionary"""
        return {
            'id': container.id,
            'container_id': container.container_id,
            'bank_id': container.bank_id,
            'policy_type_id': container.policy_type_id,
            'platform': container.platform,
            'container_name': container.container_name,
            'endpoint': container.endpoint,
            'port': container.port,
            'status': container.status,
            'health_check_url': container.health_check_url,
            'last_health_check': container.last_health_check.isoformat() if container.last_health_check else None,
            'health_status': container.health_status,
            'failure_reason': container.failure_reason,
            'document_hash': container.document_hash,
            's3_policy_url': container.s3_policy_url,
            's3_jar_url': container.s3_jar_url,
            's3_drl_url': container.s3_drl_url,
            's3_excel_url': container.s3_excel_url,
            'version': container.version,
            'is_active': container.is_active,
            'cpu_limit': container.cpu_limit,
            'memory_limit': container.memory_limit,
            'deployed_at': container.deployed_at.isoformat() if container.deployed_at else None,
            'updated_at': container.updated_at.isoformat() if container.updated_at else None,
            'stopped_at': container.stopped_at.isoformat() if container.stopped_at else None
        }

    def get_container_by_id(self, container_id: str) -> Optional[Dict[str, Any]]:
        """Get a container by its container_id as dictionary"""
        with self.get_session() as session:
            container = session.query(RuleContainer).filter_by(container_id=container_id).first()
            if not container:
                return None
            return self._container_to_dict(container)

    def get_container_by_db_id(self, db_id: int) -> Optional[Dict[str, Any]]:
        """Get a container by its database ID as dictionary"""
        with self.get_session() as session:
            container = session.query(RuleContainer).filter_by(id=db_id).first()
            if not container:
                return None
            return self._container_to_dict(container)

    def get_active_container(self, bank_id: str, policy_type_id: str) -> Optional[Dict[str, Any]]:
        """Get the active container for a bank and policy type as dictionary"""
        with self.get_session() as session:
            container = session.query(RuleContainer).filter_by(
                bank_id=bank_id,
                policy_type_id=policy_type_id,
                is_active=True
            ).first()
            if not container:
                return None
            return self._container_to_dict(container)

    def list_containers(self, bank_id: str = None, policy_type_id: str = None, status: str = None, active_only: bool = False) -> List[Dict[str, Any]]:
        """List containers with optional filters as dictionaries"""
        with self.get_session() as session:
            query = session.query(RuleContainer)

            if bank_id:
                query = query.filter_by(bank_id=bank_id)
            if policy_type_id:
                query = query.filter_by(policy_type_id=policy_type_id)
            if status:
                query = query.filter_by(status=status)
            if active_only:
                query = query.filter_by(is_active=True)

            containers = query.order_by(RuleContainer.deployed_at.desc()).all()

            # Convert to dictionaries within session context using helper
            return [self._container_to_dict(c) for c in containers]

    def update_container_status(self, container_id: str, status: str, health_status: str = None, failure_reason: str = None) -> Optional[RuleContainer]:
        """Update container status and health"""
        with self.get_session() as session:
            container = session.query(RuleContainer).filter_by(container_id=container_id).first()
            if container:
                container.status = status
                if health_status:
                    container.health_status = health_status
                container.last_health_check = datetime.utcnow()
                if failure_reason:
                    container.failure_reason = failure_reason
                if status == 'stopped':
                    container.stopped_at = datetime.utcnow()
                    container.is_active = False
                session.commit()
                session.refresh(container)
                logger.info(f"Updated container {container_id} status to {status}")
            return container

    def update_container_urls(self, container_id: str, s3_jar_url: str = None, s3_drl_url: str = None, s3_excel_url: str = None, s3_policy_url: str = None) -> Optional[RuleContainer]:
        """Update container S3 artifact URLs"""
        with self.get_session() as session:
            container = session.query(RuleContainer).filter_by(container_id=container_id).first()
            if container:
                if s3_jar_url:
                    container.s3_jar_url = s3_jar_url
                if s3_drl_url:
                    container.s3_drl_url = s3_drl_url
                if s3_excel_url:
                    container.s3_excel_url = s3_excel_url
                if s3_policy_url:
                    container.s3_policy_url = s3_policy_url
                session.commit()
                session.refresh(container)
            return container

    def delete_container(self, container_id: str) -> bool:
        """Delete a container (soft delete by marking inactive)"""
        with self.get_session() as session:
            container = session.query(RuleContainer).filter_by(container_id=container_id).first()
            if container:
                container.is_active = False
                container.status = 'stopped'
                container.stopped_at = datetime.utcnow()
                session.commit()
                logger.info(f"Deleted container {container_id}")
                return True
            return False

    # Request tracking
    def log_request(self, request_data: Dict[str, Any]) -> RuleRequest:
        """Log a rule request for analytics"""
        with self.get_session() as session:
            request = RuleRequest(**request_data)
            session.add(request)
            session.commit()
            session.refresh(request)
            return request

    def get_container_stats(self, container_id: str) -> Dict[str, Any]:
        """Get statistics for a container"""
        with self.get_session() as session:
            container = session.query(RuleContainer).filter_by(container_id=container_id).first()
            if not container:
                return None

            requests = session.query(RuleRequest).filter_by(container_id=container.id).all()

            total_requests = len(requests)
            successful_requests = sum(1 for r in requests if r.status == 'success')
            failed_requests = sum(1 for r in requests if r.status == 'error')
            avg_time = sum(r.execution_time_ms for r in requests if r.execution_time_ms) / total_requests if total_requests > 0 else 0

            return {
                'container_id': container_id,
                'total_requests': total_requests,
                'successful_requests': successful_requests,
                'failed_requests': failed_requests,
                'avg_execution_time_ms': avg_time,
                'success_rate': (successful_requests / total_requests * 100) if total_requests > 0 else 0
            }

    # Extracted Rules methods
    def save_extracted_rules(self, bank_id: str, policy_type_id: str, rules: List[Dict[str, Any]],
                            source_document: str = None, document_hash: str = None) -> List[int]:
        """
        Save extracted rules to database

        Args:
            bank_id: Bank identifier
            policy_type_id: Policy type identifier
            rules: List of extracted rules with keys: rule_name, requirement, category
            source_document: Source document name
            document_hash: Hash of source document

        Returns:
            List of created rule IDs
        """
        try:
            with self.get_session() as session:
                # Deactivate existing rules for this bank/policy combination
                session.query(ExtractedRule).filter_by(
                    bank_id=bank_id,
                    policy_type_id=policy_type_id,
                    is_active=True
                ).update({'is_active': False})

                created_ids = []
                for rule_data in rules:
                    extracted_rule = ExtractedRule(
                        bank_id=bank_id,
                        policy_type_id=policy_type_id,
                        rule_name=rule_data.get('rule_name', rule_data.get('Rule', 'Unknown Rule')),
                        requirement=rule_data.get('requirement', rule_data.get('Requirement', '')),
                        category=rule_data.get('category', rule_data.get('Category', 'General')),
                        source_document=source_document or rule_data.get('source_document', rule_data.get('Source Document', '')),
                        document_hash=document_hash,
                        is_active=True
                    )
                    session.add(extracted_rule)
                    session.flush()
                    created_ids.append(extracted_rule.id)

                session.commit()
                logger.info(f"Saved {len(created_ids)} extracted rules for {bank_id}/{policy_type_id}")
                return created_ids

        except Exception as e:
            logger.error(f"Error saving extracted rules: {e}")
            return []

    def get_extracted_rules(self, bank_id: str, policy_type_id: str, active_only: bool = True) -> List[Dict[str, Any]]:
        """
        Get extracted rules for a bank and policy type

        Args:
            bank_id: Bank identifier
            policy_type_id: Policy type identifier
            active_only: Only return active rules

        Returns:
            List of rule dictionaries
        """
        try:
            with self.get_session() as session:
                query = session.query(ExtractedRule).filter_by(
                    bank_id=bank_id,
                    policy_type_id=policy_type_id
                )

                if active_only:
                    query = query.filter_by(is_active=True)

                rules = query.order_by(ExtractedRule.category, ExtractedRule.rule_name).all()

                return [{
                    'id': rule.id,
                    'rule_name': rule.rule_name,
                    'requirement': rule.requirement,
                    'category': rule.category,
                    'source_document': rule.source_document,
                    'document_hash': rule.document_hash,
                    'extraction_timestamp': rule.extraction_timestamp.isoformat() if rule.extraction_timestamp else None,
                    'is_active': rule.is_active,
                    'created_at': rule.created_at.isoformat() if rule.created_at else None,
                    'updated_at': rule.updated_at.isoformat() if rule.updated_at else None
                } for rule in rules]

        except Exception as e:
            logger.error(f"Error fetching extracted rules: {e}")
            return []

    def delete_extracted_rules(self, bank_id: str, policy_type_id: str) -> bool:
        """
        Delete all extracted rules for a bank and policy type

        Args:
            bank_id: Bank identifier
            policy_type_id: Policy type identifier

        Returns:
            True if successful, False otherwise
        """
        try:
            with self.get_session() as session:
                session.query(ExtractedRule).filter_by(
                    bank_id=bank_id,
                    policy_type_id=policy_type_id
                ).delete()
                session.commit()
                logger.info(f"Deleted extracted rules for {bank_id}/{policy_type_id}")
                return True
        except Exception as e:
            logger.error(f"Error deleting extracted rules: {e}")
            return False

    # Utility methods
    def health_check(self) -> bool:
        """Check database connectivity"""
        try:
            with self.get_session() as session:
                session.execute(text("SELECT 1"))
            return True
        except Exception as e:
            logger.error(f"Database health check failed: {e}")
            return False

    def get_banks_with_policies(self) -> List[Dict[str, Any]]:
        """Get all banks with their available policy types"""
        with self.get_session() as session:
            banks = session.query(Bank).filter_by(is_active=True).all()
            result = []

            for bank in banks:
                containers = session.query(RuleContainer).filter_by(
                    bank_id=bank.bank_id,
                    is_active=True
                ).all()

                policies = list(set([c.policy_type_id for c in containers]))

                result.append({
                    'bank_id': bank.bank_id,
                    'bank_name': bank.bank_name,
                    'available_policies': policies,
                    'total_containers': len(containers)
                })

            return result


# Singleton instance
_db_service_instance = None

def get_database_service() -> DatabaseService:
    """Get or create database service singleton"""
    global _db_service_instance
    if _db_service_instance is None:
        _db_service_instance = DatabaseService()
    return _db_service_instance
