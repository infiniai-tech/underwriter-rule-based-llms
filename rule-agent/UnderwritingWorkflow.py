#
#    Copyright 2024 IBM Corp.
#
#    Licensed under the Apache License, Version 2.0 (the "License");
#    you may not use this file except in compliance with the License.
#    You may obtain a copy of the License at
#
#        http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS,
#    WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#    See the License for the specific language governing permissions and
#    limitations under the License.
#
from PolicyAnalyzerAgent import PolicyAnalyzerAgent
from TextractService import TextractService
from RuleGeneratorAgent import RuleGeneratorAgent
from HierarchicalRulesAgent import HierarchicalRulesAgent
from DroolsDeploymentService import DroolsDeploymentService
from S3Service import S3Service
from ExcelRulesExporter import ExcelRulesExporter
from DatabaseService import get_database_service
from DocumentExtractor import DocumentExtractor
from PyPDF2 import PdfReader
import json
import os
import io
from typing import Dict, List, Optional
from langchain_openai import ChatOpenAI
import hashlib

class UnderwritingWorkflow:
    """
    Orchestrates the complete underwriting workflow:
    Multi-format Document (PDF/Excel/Word) → Analysis → Textract → Rule Generation → Deployment → Excel Export

    Supported document formats:
    - PDF (.pdf) - via PyPDF2 and AWS Textract
    - Excel (.xlsx, .xls) - via pandas/openpyxl
    - Word (.docx) - via python-docx
    - Text (.txt) - direct read
    """

    def __init__(self, llm):
        self.llm = llm
        self.policy_analyzer = PolicyAnalyzerAgent(llm)
        self.textract = TextractService()
        self.rule_generator = RuleGeneratorAgent(llm)
        self.hierarchical_rules_agent = HierarchicalRulesAgent(llm)
        self.drools_deployment = DroolsDeploymentService()
        self.s3_service = S3Service()
        self.excel_exporter = ExcelRulesExporter()
        self.db_service = get_database_service()
        self.document_extractor = DocumentExtractor()

        # Validate Textract is configured (required for PDF query-based extraction)
        if not self.textract.isConfigured:
            print("WARNING: AWS Textract is not configured. PDF query-based extraction will not be available.")
            print("         Excel and Word documents will still work with text-based extraction.")

    def process_policy_document(self, s3_url: str,
                                policy_type: str = "general",
                                bank_id: str = None) -> Dict:
        """
        Complete workflow to process a policy document and generate rules

        :param s3_url: S3 URL to policy PDF (required)
        :param policy_type: Type of policy (general, life, health, auto, property, loan, insurance, etc.)
        :param bank_id: Bank/Tenant identifier (e.g., 'chase', 'bofa', 'wells-fargo')
        :return: Result dictionary with all workflow steps
        """

        # Auto-generate container_id based on bank_id and policy_type
        # This ensures proper multi-tenant isolation
        # Normalize policy_type: lowercase and replace spaces with hyphens
        normalized_type = policy_type.lower().strip().replace(' ', '-')

        if bank_id:
            # Normalize bank_id: lowercase and replace spaces with hyphens
            normalized_bank = bank_id.lower().strip().replace(' ', '-')
            container_id = f"{normalized_bank}-{normalized_type}-underwriting-rules"
            print(f"Auto-generated container ID (with bank): {container_id}")
        else:
            # Fallback to policy-type only (for backwards compatibility)
            container_id = f"{normalized_type}-underwriting-rules"
            print(f"Auto-generated container ID (no bank): {container_id}")
            print("Warning: No bank_id provided. Consider specifying bank_id for multi-tenant deployments.")

        result = {
            "s3_url": s3_url,
            "policy_type": policy_type,
            "bank_id": bank_id,
            "container_id": container_id,
            "steps": {},
            "status": "in_progress"
        }

        try:
            # Step 0.1: Ensure bank exists in database (auto-create if missing)
            if bank_id:
                try:
                    print("\n" + "="*60)
                    print("Step 0.1: Ensuring bank exists in database...")
                    print("="*60)

                    existing_bank = self.db_service.get_bank(normalized_bank)
                    if not existing_bank:
                        # Auto-create bank with normalized ID
                        bank_name = normalized_bank.replace('-', ' ').title()
                        self.db_service.create_bank(
                            bank_id=normalized_bank,
                            bank_name=bank_name,
                            description=f"Auto-created bank: {bank_name}"
                        )
                        print(f"✓ Created bank: {normalized_bank} ({bank_name})")
                        result["steps"]["bank_creation"] = {
                            "status": "created",
                            "bank_id": normalized_bank,
                            "bank_name": bank_name
                        }
                    else:
                        print(f"✓ Bank already exists: {normalized_bank}")
                        result["steps"]["bank_creation"] = {
                            "status": "exists",
                            "bank_id": normalized_bank
                        }
                except Exception as e:
                    print(f"⚠ Error checking/creating bank: {e}")
                    result["steps"]["bank_creation"] = {
                        "status": "error",
                        "error": str(e)
                    }
                    # Continue anyway - let foreign key constraints catch if there's a real issue

            # Step 0.2: Ensure policy type exists in database (auto-create if missing)
            if policy_type:
                try:
                    print("\n" + "="*60)
                    print("Step 0.2: Ensuring policy type exists in database...")
                    print("="*60)

                    existing_policy = self.db_service.get_policy_type(normalized_type)
                    if not existing_policy:
                        # Auto-create policy type with normalized ID
                        policy_name = normalized_type.replace('-', ' ').title()
                        self.db_service.create_policy_type(
                            policy_type_id=normalized_type,
                            policy_name=policy_name,
                            description=f"Auto-created policy type: {policy_name}",
                            category=normalized_type
                        )
                        print(f"✓ Created policy type: {normalized_type} ({policy_name})")
                        result["steps"]["policy_type_creation"] = {
                            "status": "created",
                            "policy_type_id": normalized_type,
                            "policy_name": policy_name
                        }
                    else:
                        print(f"✓ Policy type already exists: {normalized_type}")
                        result["steps"]["policy_type_creation"] = {
                            "status": "exists",
                            "policy_type_id": normalized_type
                        }
                except Exception as e:
                    print(f"⚠ Error checking/creating policy type: {e}")
                    result["steps"]["policy_type_creation"] = {
                        "status": "error",
                        "error": str(e)
                    }
                    # Continue anyway - let foreign key constraints catch if there's a real issue

            # Parse S3 URL to extract bucket and key
            print("\n" + "="*60)
            print("Step 0: Parsing S3 URL...")
            print("="*60)

            s3_info = self.s3_service.parse_s3_url(s3_url)
            if "error" in s3_info:
                result["status"] = "failed"
                result["error"] = s3_info["error"]
                return result

            s3_bucket = s3_info["bucket"]
            s3_key = s3_info["key"]
            print(f"✓ S3 bucket: {s3_bucket}")
            print(f"✓ S3 key: {s3_key}")
            result["s3_bucket"] = s3_bucket
            result["s3_key"] = s3_key

            # Step 1: Extract text from document (auto-detect format: PDF, Excel, Word, Text)
            print("\n" + "="*60)
            print("Step 1: Extracting text from document (auto-detecting format)...")
            print("="*60)

            # Use new DocumentExtractor to handle multiple formats
            extraction_result = self.document_extractor.extract_text_from_s3(s3_url)

            if "error" in extraction_result:
                result["status"] = "failed"
                result["error"] = f"Text extraction failed: {extraction_result['error']}"
                return result

            document_text = extraction_result["text"]
            document_format = extraction_result["format"]

            result["steps"]["text_extraction"] = {
                "status": "success",
                "format": document_format,
                "length": len(document_text),
                "preview": document_text[:500] + "..." if len(document_text) > 500 else document_text
            }
            print(f"✓ Detected format: {document_format.upper()}")
            print(f"✓ Extracted {len(document_text)} characters")

            # Compute document hash for version tracking
            document_hash = hashlib.sha256(document_text.encode('utf-8')).hexdigest()
            result["document_hash"] = document_hash

            # Step 2: LLM generates extraction queries by analyzing the document
            print("\n" + "="*60)
            print("Step 2: LLM analyzing document and generating extraction queries...")
            print("="*60)

            analysis = self.policy_analyzer.analyze_policy(document_text)
            queries = analysis.get("queries", [])
            result["steps"]["query_generation"] = {
                "status": "success",
                "method": "llm_generated",
                "queries": queries,
                "count": len(queries),
                "key_sections": analysis.get("key_sections", []),
                "rule_categories": analysis.get("rule_categories", [])
            }

            print(f"✓ LLM generated {len(queries)} custom queries")
            for i, q in enumerate(queries, 1):
                print(f"  {i}. {q}")

            # Step 3: Extract structured data using AWS Textract
            print("\n" + "="*60)
            print("Step 3: Extracting structured data with AWS Textract...")
            print("="*60)

            if len(queries) == 0:
                raise ValueError("No extraction queries generated. Cannot proceed with data extraction.")

            print("Using AWS Textract for data extraction from S3...")
            # Use S3 document directly with Textract
            extracted_data = self.textract.analyze_document(
                s3_bucket=s3_bucket,
                s3_key=s3_key,
                queries=queries
            )

            result["steps"]["data_extraction"] = {
                "status": "success",
                "method": "textract",
                "data": extracted_data
            }
            print(f"✓ Extracted data from {len(queries)} queries using AWS Textract")

            # Step 3.5: Save extraction queries and Textract responses to database
            if bank_id and policy_type:
                try:
                    print("\n" + "="*60)
                    print("Step 3.5: Saving extraction queries and responses to database...")
                    print("="*60)

                    # Prepare queries data for database
                    queries_data = []
                    textract_queries = extracted_data.get('queries', {})

                    for query_text in queries:
                        query_info = textract_queries.get(query_text, {})
                        queries_data.append({
                            'query_text': query_text,
                            'response_text': query_info.get('answer', ''),
                            'confidence_score': query_info.get('confidence', None),
                            'extraction_method': 'textract'
                        })

                    # Save to database (use normalized IDs)
                    saved_query_ids = self.db_service.save_extraction_queries(
                        bank_id=normalized_bank if bank_id else None,
                        policy_type_id=normalized_type,
                        queries_data=queries_data,
                        document_hash=document_hash,
                        source_document=s3_url
                    )

                    print(f"✓ Saved {len(saved_query_ids)} extraction queries to database")
                    result["steps"]["save_extraction_queries"] = {
                        "status": "success",
                        "count": len(saved_query_ids),
                        "query_ids": saved_query_ids
                    }

                except Exception as e:
                    print(f"⚠ Failed to save extraction queries to database: {e}")
                    result["steps"]["save_extraction_queries"] = {
                        "status": "error",
                        "message": str(e)
                    }

            # Step 4: Generate Drools rules
            print("\n" + "="*60)
            print("Step 4: Generating Drools rules...")
            print("="*60)

            rules = self.rule_generator.generate_rules(extracted_data)
            result["steps"]["rule_generation"] = {
                "status": "success",
                "drl_length": len(rules.get('drl', '')),
                "has_decision_table": rules.get('decision_table') is not None and len(rules.get('decision_table', '')) > 0,
                "explanation": rules.get('explanation', '')
            }
            print(f"✓ Generated DRL rules ({len(rules.get('drl', ''))} characters)")
            if rules.get('decision_table'):
                print(f"✓ Generated decision table")

            # Step 4.5: Save extracted rules to database (from DRL content)
            if bank_id and policy_type and rules.get('drl'):
                try:
                    print("\n" + "="*60)
                    print("Step 4.5: Parsing and saving rules from DRL to database...")
                    print("="*60)

                    # Parse DRL content to extract actual rules
                    drl_content = rules.get('drl', '')
                    rules_for_db = self._parse_drl_rules(drl_content)

                    if rules_for_db:
                        # Save to database (use normalized IDs)
                        saved_ids = self.db_service.save_extracted_rules(
                            bank_id=normalized_bank if bank_id else None,
                            policy_type_id=normalized_type,
                            rules=rules_for_db,
                            source_document=s3_key,
                            document_hash=document_hash
                        )

                        print(f"✓ Saved {len(saved_ids)} Drools rules to database")
                        result["steps"]["save_drools_rules"] = {
                            "status": "success",
                            "count": len(saved_ids),
                            "rule_ids": saved_ids
                        }
                    else:
                        print("⚠ No parseable rules found in DRL content")

                except Exception as e:
                    print(f"⚠ Failed to save Drools rules to database: {e}")
                    result["steps"]["save_drools_rules"] = {
                        "status": "error",
                        "message": str(e)
                    }

            # Step 4.6: Generate and save hierarchical rules using LLM
            if bank_id and policy_type:
                try:
                    print("\n" + "="*60)
                    print("Step 4.6: Generating hierarchical rules with LLM...")
                    print("="*60)

                    # Generate hierarchical rules from policy text
                    hierarchical_rules = self.hierarchical_rules_agent.generate_hierarchical_rules(
                        policy_text=document_text,
                        policy_type=policy_type
                    )

                    # Save to database (use normalized IDs)
                    if hierarchical_rules:
                        saved_rule_ids = self.db_service.save_hierarchical_rules(
                            bank_id=normalized_bank if bank_id else None,
                            policy_type_id=normalized_type,
                            rules_tree=hierarchical_rules,
                            document_hash=document_hash,
                            source_document=s3_key
                        )

                        print(f"✓ Saved {len(saved_rule_ids)} hierarchical rules to database")
                        result["steps"]["save_hierarchical_rules"] = {
                            "status": "success",
                            "count": len(saved_rule_ids),
                            "top_level_rules": len(hierarchical_rules),
                            "rule_ids": saved_rule_ids
                        }
                    else:
                        print("⚠ No hierarchical rules generated")
                        result["steps"]["save_hierarchical_rules"] = {
                            "status": "warning",
                            "message": "No hierarchical rules generated"
                        }

                except Exception as e:
                    print(f"⚠ Failed to generate/save hierarchical rules: {e}")
                    import traceback
                    traceback.print_exc()
                    result["steps"]["save_hierarchical_rules"] = {
                        "status": "error",
                        "message": str(e)
                    }

            # Step 5: Automated deployment to Drools KIE Server (includes DRL save)
            print("\n" + "="*60)
            print("Step 5: Automated deployment to Drools KIE Server...")
            print("="*60)

            # Try automated deployment (KJar creation, Maven build, deployment)
            deployment_result = self.drools_deployment.deploy_rules_automatically(
                rules['drl'],
                container_id
            )
            result["steps"]["deployment"] = deployment_result

            if deployment_result["status"] == "success":
                print(f"✓ Rules automatically deployed to container '{container_id}'")
            elif deployment_result["status"] == "partial":
                print(f"⚠ Partial success: {deployment_result['message']}")
                if "manual_instructions" in deployment_result:
                    print(f"  Manual step required: {deployment_result['manual_instructions']}")
            else:
                print(f"✗ Deployment failed: {deployment_result.get('message', 'Unknown error')}")

            # Also save KJar info in a separate step for clarity
            if "steps" in deployment_result and "create_kjar" in deployment_result["steps"]:
                result["steps"]["kjar_creation"] = deployment_result["steps"]["create_kjar"]

            # Step 6: Upload JAR and DRL to S3 if built successfully
            if deployment_result.get("steps", {}).get("build", {}).get("status") == "success":
                print("\n" + "="*60)
                print("Step 6: Uploading generated files to S3...")
                print("="*60)

                jar_path = deployment_result["steps"]["build"].get("jar_path")
                drl_path = deployment_result["steps"]["save_drl"].get("path")
                version = deployment_result["release_id"]["version"]

                s3_upload_results = {}

                # Upload JAR file
                if jar_path and os.path.exists(jar_path):
                    jar_upload = self.s3_service.upload_jar_to_s3(jar_path, container_id, version)
                    s3_upload_results["jar"] = jar_upload
                    if jar_upload["status"] == "success":
                        print(f"✓ JAR uploaded to S3: {jar_upload['s3_url']}")
                        result["jar_s3_url"] = jar_upload["s3_url"]
                        # Generate pre-signed URL for JAR
                        jar_presigned = self.s3_service.generate_presigned_url_from_s3_url(jar_upload["s3_url"], expiration=86400)  # 24 hours
                        if jar_presigned:
                            result["jar_presigned_url"] = jar_presigned
                    else:
                        print(f"✗ JAR upload failed: {jar_upload.get('message', 'Unknown error')}")

                    # Clean up temp JAR file after upload
                    try:
                        os.unlink(jar_path)
                        print(f"✓ Temporary JAR file deleted: {jar_path}")
                    except Exception as e:
                        print(f"Warning: Could not delete temp JAR file: {e}")

                # Upload DRL file
                drl_content = None
                if drl_path and os.path.exists(drl_path):
                    # Read DRL content for Excel export
                    with open(drl_path, 'r', encoding='utf-8') as f:
                        drl_content = f.read()

                    drl_upload = self.s3_service.upload_drl_to_s3(drl_path, container_id, version)
                    s3_upload_results["drl"] = drl_upload
                    if drl_upload["status"] == "success":
                        print(f"✓ DRL uploaded to S3: {drl_upload['s3_url']}")
                        result["drl_s3_url"] = drl_upload["s3_url"]
                        # Generate pre-signed URL for DRL
                        drl_presigned = self.s3_service.generate_presigned_url_from_s3_url(drl_upload["s3_url"], expiration=86400)  # 24 hours
                        if drl_presigned:
                            result["drl_presigned_url"] = drl_presigned
                    else:
                        print(f"✗ DRL upload failed: {drl_upload.get('message', 'Unknown error')}")

                    # Clean up temp DRL file after upload
                    try:
                        os.unlink(drl_path)
                        print(f"✓ Temporary DRL file deleted: {drl_path}")
                    except Exception as e:
                        print(f"Warning: Could not delete temp DRL file: {e}")

                # Generate and upload Excel spreadsheet with rules
                if drl_content:
                    try:
                        print("✓ Generating Excel spreadsheet from rules...")
                        # Use container_id as fallback if bank_id is not provided
                        effective_bank_id = bank_id if bank_id else policy_type
                        excel_path = self.excel_exporter.create_excel_file(
                            drl_content, effective_bank_id, policy_type, container_id, version
                        )

                        # Upload Excel to S3
                        excel_upload = self.s3_service.upload_excel_to_s3(
                            excel_path, bank_id, policy_type, container_id, version
                        )
                        s3_upload_results["excel"] = excel_upload

                        if excel_upload["status"] == "success":
                            print(f"✓ Excel spreadsheet uploaded to S3: {excel_upload['s3_url']}")
                            result["excel_s3_url"] = excel_upload["s3_url"]
                            # Generate pre-signed URL for Excel
                            excel_presigned = self.s3_service.generate_presigned_url_from_s3_url(excel_upload["s3_url"], expiration=86400)  # 24 hours
                            if excel_presigned:
                                result["excel_presigned_url"] = excel_presigned
                        else:
                            print(f"✗ Excel upload failed: {excel_upload.get('message', 'Unknown error')}")

                        # Clean up temp Excel file
                        try:
                            os.unlink(excel_path)
                            print(f"✓ Temporary Excel file deleted: {excel_path}")
                        except Exception as e:
                            print(f"Warning: Could not delete temp Excel file: {e}")

                    except Exception as e:
                        print(f"⚠ Excel generation failed: {e}")
                        s3_upload_results["excel"] = {
                            "status": "error",
                            "message": str(e)
                        }

                result["steps"]["s3_upload"] = s3_upload_results

                # Generate pre-signed URL for the original policy document
                if s3_url:
                    policy_presigned = self.s3_service.generate_presigned_url_from_s3_url(s3_url, expiration=86400)  # 24 hours
                    if policy_presigned:
                        result["policy_presigned_url"] = policy_presigned
                        print(f"✓ Generated pre-signed URL for policy document")

                # Update database with S3 URLs
                try:
                    print("\n" + "="*60)
                    print("Step 6.5: Updating container registry in database...")
                    print("="*60)

                    # Ensure bank and policy type exist in database
                    if bank_id:
                        self.db_service.create_bank(bank_id, bank_id.replace('_', ' ').title())
                    self.db_service.create_policy_type(policy_type, policy_type.replace('_', ' ').title())

                    # Update container with S3 URLs
                    container = self.db_service.get_container_by_id(container_id)
                    if container:
                        # Container exists (created by ContainerOrchestrator), update URLs
                        self.db_service.update_container_urls(
                            container_id,
                            s3_jar_url=result.get("jar_s3_url"),
                            s3_drl_url=result.get("drl_s3_url"),
                            s3_excel_url=result.get("excel_s3_url"),
                            s3_policy_url=s3_url
                        )
                        print(f"✓ Updated container {container_id} in database with S3 URLs")
                    else:
                        # Container doesn't exist yet (manual deployment or error), create entry
                        print(f"⚠ Container {container_id} not found in database - may need manual registration")

                except Exception as db_error:
                    print(f"⚠ Failed to update database: {db_error}")
                    # Don't fail the workflow for database errors
                    result["database_update_error"] = str(db_error)

            result["status"] = "completed"
            result["source"] = "generated"

            print("\n" + "="*60)
            print("✓ Workflow completed successfully!")
            print("="*60)

        except Exception as e:
            print(f"\n✗ Error in workflow: {e}")
            result["status"] = "failed"
            result["error"] = str(e)

        return result

    def _extract_text_from_s3(self, s3_key: str) -> str:
        """Extract text from S3 PDF directly into memory using PyPDF2"""
        try:
            # Read PDF bytes from S3 directly into memory
            pdf_bytes = self.s3_service.read_pdf_from_s3(s3_key)
            if not pdf_bytes:
                return "Error: Could not read PDF from S3"

            # Create a BytesIO object and use PyPDF2 to read it
            pdf_file = io.BytesIO(pdf_bytes)
            reader = PdfReader(pdf_file)

            text = ""
            for page_num, page in enumerate(reader.pages, 1):
                page_text = page.extract_text()
                text += f"\n--- Page {page_num} ---\n{page_text}"

            print(f"✓ Extracted text from S3 PDF ({len(reader.pages)} pages)")
            return text
        except Exception as e:
            print(f"Error extracting text from S3 PDF: {e}")
            return f"Error: Could not extract text from S3 PDF - {str(e)}"

    def _parse_drl_rules(self, drl_content: str) -> List[Dict[str, str]]:
        """
        Parse DRL content to extract individual rules with their conditions and actions
        Returns list of rules in format suitable for database storage
        """
        import re

        rules_list = []

        try:
            # Split DRL into individual rule blocks
            # Pattern: rule "RuleName" ... when ... then ... end
            rule_pattern = r'rule\s+"([^"]+)"[^w]*?when(.*?)then(.*?)end'
            matches = re.finditer(rule_pattern, drl_content, re.DOTALL | re.IGNORECASE)

            for idx, match in enumerate(matches, 1):
                rule_name = match.group(1).strip()
                when_clause = match.group(2).strip()
                then_clause = match.group(3).strip()

                # Clean up the clauses
                when_clause = self._clean_drl_clause(when_clause)
                then_clause = self._clean_drl_clause(then_clause)

                # Determine category based on rule name or content
                category = self._categorize_rule(rule_name, when_clause)

                # Transform technical Drools rule into user-friendly text
                user_friendly_requirement = self._transform_rule_to_user_friendly(
                    rule_name, when_clause, then_clause
                )

                rules_list.append({
                    "rule_name": rule_name,
                    "requirement": user_friendly_requirement,
                    "category": category,
                    "source_document": "Generated from policy document"
                })

            # If no rules found with standard pattern, try to extract from decision table comments
            if not rules_list:
                print("⚠ No standard rules found, attempting to parse decision table...")
                rules_list = self._parse_decision_table(drl_content)

        except Exception as e:
            print(f"Error parsing DRL rules: {e}")

        return rules_list

    def _clean_drl_clause(self, clause: str) -> str:
        """Clean up DRL clause by removing extra whitespace and formatting"""
        # Remove extra whitespace
        clause = ' '.join(clause.split())
        # Remove semicolons at the end
        clause = clause.rstrip(';')
        return clause

    def _transform_rule_to_user_friendly(self, rule_name: str, when_clause: str, then_clause: str) -> str:
        """
        Transform technical Drools WHEN/THEN clauses into user-friendly requirement text
        using OpenAI GPT
        """
        try:
            # Get OpenAI API key from environment
            openai_api_key = os.getenv('OPENAI_API_KEY')
            if not openai_api_key:
                print("⚠ OpenAI API key not configured, returning technical format")
                return f"WHEN: {when_clause}\nTHEN: {then_clause}"

            # Initialize OpenAI client
            llm = ChatOpenAI(
                model=os.getenv('OPENAI_MODEL_NAME', 'gpt-4'),
                temperature=0.3,  # Lower temperature for consistent transformation
                openai_api_key=openai_api_key
            )

            # Create prompt for transformation
            prompt = f"""Transform the following technical Drools rule into a clear, user-friendly requirement statement.

Rule Name: {rule_name}

Technical Rule:
WHEN: {when_clause}
THEN: {then_clause}

Instructions:
1. Write a concise, natural language statement that explains what this rule checks
2. Focus on the business requirement, not technical implementation
3. Use simple language that a non-technical user can understand
4. Include specific values and thresholds mentioned in the rule
5. Format: Write as a single clear statement or short paragraph (maximum 2-3 sentences)
6. Do NOT include technical terms like "Applicant", "$applicant", "Decision", etc.
7. Use phrases like "must be", "should be", "required", etc.

Example transformations:
- Technical: "WHEN: $applicant : Applicant( age < 18 || age > 65 ) THEN: $decision.setApproved(false)"
- User-friendly: "Applicant must be between 18 and 65 years old"

- Technical: "WHEN: $applicant : Applicant( creditScore < 600 ) THEN: $decision.setApproved(false)"
- User-friendly: "Minimum credit score of 600 is required"

Now transform the rule above:"""

            # Get response from OpenAI
            response = llm.invoke(prompt)
            user_friendly_text = response.content.strip()

            # Validate response is not empty
            if not user_friendly_text or len(user_friendly_text) < 10:
                print(f"⚠ OpenAI returned short response for rule '{rule_name}', using fallback")
                return self._fallback_transformation(rule_name, when_clause, then_clause)

            return user_friendly_text

        except Exception as e:
            print(f"⚠ Error transforming rule '{rule_name}' with OpenAI: {e}")
            return self._fallback_transformation(rule_name, when_clause, then_clause)

    def _fallback_transformation(self, rule_name: str, when_clause: str, then_clause: str) -> str:
        """
        Fallback transformation using simple pattern matching when OpenAI is not available
        """
        import re

        # Extract key information from WHEN clause
        when_lower = when_clause.lower()

        # Age rules
        if 'age' in when_lower:
            age_match = re.search(r'age\s*([<>=!]+)\s*(\d+)', when_lower)
            if age_match:
                operator = age_match.group(1)
                value = age_match.group(2)
                if '<' in operator:
                    return f"Minimum age requirement of {value} years"
                elif '>' in operator:
                    return f"Maximum age limit of {value} years"

        # Credit score rules
        if 'credit' in when_lower:
            credit_match = re.search(r'credit\w*\s*([<>=!]+)\s*(\d+)', when_lower)
            if credit_match:
                operator = credit_match.group(1)
                value = credit_match.group(2)
                if '<' in operator:
                    return f"Minimum credit score of {value} is required"
                elif '>' in operator:
                    return f"Credit score must not exceed {value}"

        # Income rules
        if 'income' in when_lower:
            income_match = re.search(r'income\s*([<>=!]+)\s*(\d+)', when_lower)
            if income_match:
                operator = income_match.group(1)
                value = income_match.group(2)
                if '<' in operator:
                    return f"Minimum annual income of ${value:,} is required"
                elif '>' in operator:
                    return f"Annual income must not exceed ${value:,}"

        # Coverage amount rules
        if 'coverage' in when_lower:
            coverage_match = re.search(r'coverage\w*\s*([<>=!]+)\s*(\d+)', when_lower)
            if coverage_match:
                operator = coverage_match.group(1)
                value = coverage_match.group(2)
                if '>' in operator:
                    return f"Maximum coverage amount of ${int(value):,}"
                elif '<' in operator:
                    return f"Minimum coverage amount of ${int(value):,}"

        # Health condition rules
        if 'health' in when_lower and 'poor' in when_lower:
            return "Applicants with poor health status are not eligible"

        # Smoker rules
        if 'smoker' in when_lower and 'true' in when_lower:
            if 'premium' in then_clause.lower():
                multiplier_match = re.search(r'(\d+\.?\d*)', then_clause)
                if multiplier_match:
                    multiplier = float(multiplier_match.group(1))
                    increase_pct = int((multiplier - 1) * 100)
                    return f"Smokers pay {increase_pct}% higher premiums"
            return "Special premium rates apply for smokers"

        # Default fallback - simplified technical format
        return f"Rule: {rule_name}"

    def _categorize_rule(self, rule_name: str, when_clause: str) -> str:
        """Determine category based on rule name and conditions"""
        rule_name_lower = rule_name.lower()
        when_lower = when_clause.lower()

        if 'age' in rule_name_lower or 'age' in when_lower:
            return "Age Requirements"
        elif 'credit' in rule_name_lower or 'credit' in when_lower:
            return "Credit Score Requirements"
        elif 'income' in rule_name_lower or 'income' in when_lower:
            return "Income Requirements"
        elif 'health' in rule_name_lower or 'health' in when_lower:
            return "Health Requirements"
        elif 'reject' in rule_name_lower or 'reject' in when_lower:
            return "Automatic Rejection Criteria"
        elif 'coverage' in rule_name_lower or 'coverage' in when_lower:
            return "Coverage Requirements"
        elif 'premium' in rule_name_lower or 'premium' in when_lower:
            return "Premium Calculation"
        elif 'tier' in rule_name_lower:
            return "Coverage Tiers"
        elif 'approval' in rule_name_lower or 'approve' in rule_name_lower:
            return "Approval Rules"
        else:
            return "General Requirements"

    def _parse_decision_table(self, drl_content: str) -> List[Dict[str, str]]:
        """Parse decision table format rules from DRL"""
        rules_list = []

        try:
            # Look for decision table comments or structure
            lines = drl_content.split('\n')
            current_rule = None

            for line in lines:
                line = line.strip()
                # Skip empty lines and package/import statements
                if not line or line.startswith('package') or line.startswith('import'):
                    continue

                # Look for rule definitions in decision table format
                if line.startswith('//') or line.startswith('#'):
                    # This might be a comment describing a rule
                    comment = line.lstrip('/#').strip()
                    if len(comment) > 10:  # Substantial comment
                        rules_list.append({
                            "rule_name": f"Rule {len(rules_list) + 1}",
                            "requirement": comment,
                            "category": "Policy Rules",
                            "source_document": "Generated from policy document"
                        })

        except Exception as e:
            print(f"Error parsing decision table: {e}")

        return rules_list

