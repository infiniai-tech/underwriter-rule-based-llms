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
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
from RuleAIAgent import RuleAIAgent
from AIAgent import AIAgent
from RuleAIAgent2 import RuleAIAgent2
from CreateLLM import createLLM
from ODMService import ODMService
from ADSService import ADSService
from DroolsService import DroolsService
from UnderwritingWorkflow import UnderwritingWorkflow
from RuleCacheService import get_rule_cache
from DatabaseService import get_database_service
from S3Service import S3Service
import json,os
from Utils import find_descriptors
from werkzeug.utils import secure_filename

ROUTE="/rule-agent"

# Initialize database service
db_service = get_database_service()

app = Flask(__name__)
cors = CORS(app)
app.config['CORS_HEADERS'] = 'Content-Type'

# create a LLM service
llm = createLLM()

# print("Using LLM model: ", llm.model_id)


# Create all decision services - always return all services even if not connected
# Tool descriptors need to access services by name, so we include all of them
def get_rule_services():
    services = {
        "ads": adsService,
        "drools": droolsService,
        "odm": odmService
    }
    return services

# create Decision services
adsService = ADSService()
droolsService = DroolsService()
odmService = ODMService()
ruleServices = get_rule_services()

# create Decision services (ODM and ADS)
#odmService = ODMService()
#adsService = ADSService()
#ruleServices = { "odm": odmService, "ads": adsService}

# create an AI Agent using Decision Services
ruleAIAgent = RuleAIAgent(llm, ruleServices)
# alternative way to implement a chain using tools
# ruleAIAgent = RuleAIAgent2(llm, ruleServices)

# create an AI Agent using RAG only
aiAgent = AIAgent(llm)

# create Underwriting Workflow
underwritingWorkflow = UnderwritingWorkflow(llm)

# create S3 Service for file uploads
s3Service = S3Service()

def ingestAllDocuments(directory_path):
    """Reads all PDF files in a directory and returns a list of document to load.

    :param directory_path: The path to the directory containing the JSON files.
    :return: A list of ToolDescriptor instances.
    """
    for filename in os.listdir(directory_path):
        if filename.endswith(".pdf"):
            file_path = os.path.join(directory_path, filename)
            print("Ingesting document : "+file_path)
            aiAgent.ingestDocument(file_path)

catalog_dirs = find_descriptors('catalog')
for directory in catalog_dirs:
    ingestAllDocuments(directory)
    
# Web Service routes

@app.route(ROUTE + '/chat_with_tools', methods=['GET'])
def chat_with_tools():
    if (not odmService.isConnected):
        print("Error: Not connected to any Decision runtime")
        return {'output' : 'Not connected to any Decision runtime', 'type' : 'error'}

    userInput = request.args.get('userMessage')    
    print("chat_with_tools: received request ", userInput) 
    response = ruleAIAgent.processMessage(userInput)    
    # response = ruleAIAgent2.processMessage(userInput)
    # print("response: ", response)  
    return response

@app.route(ROUTE + '/chat_without_tools', methods=['GET'])
def chat_without_tools():
    userInput = request.args.get('userMessage')
    print("chat_without_tools: received request ", userInput)
    response = aiAgent.processMessage(userInput)
    # print("response: ", response)
    return response

# New endpoints for underwriting workflow

@app.route(ROUTE + '/upload_policy', methods=['POST'])
def upload_policy():
    """DEPRECATED: Local file upload is no longer supported. Use /process_policy_from_s3 instead."""
    return jsonify({
        'error': 'Local file upload is deprecated. Please upload your PDF to S3 and use /process_policy_from_s3 endpoint instead.',
        'status': 'deprecated'
    }), 400

@app.route(ROUTE + '/process_policy_from_s3', methods=['POST'])
def process_policy_from_s3():
    """Process a policy PDF from S3 URL through the underwriting workflow"""
    data = request.get_json()

    if not data:
        return jsonify({'error': 'JSON body is required'}), 400

    # Validate required fields
    if 's3_url' not in data:
        return jsonify({'error': 's3_url is required in JSON body'}), 400

    if 'policy_type' not in data:
        return jsonify({'error': 'policy_type is required in JSON body (e.g., "life_insurance", "auto", "property")'}), 400

    if 'bank_id' not in data:
        return jsonify({'error': 'bank_id is required in JSON body (e.g., "chase", "bofa", "wells-fargo")'}), 400

    s3_url = data['s3_url']
    policy_type = data['policy_type']
    bank_id = data['bank_id']

    # Process through workflow with S3 URL
    # container_id is auto-generated from bank_id and policy_type
    # LLM generates queries by analyzing the document
    # Rules are transformed to user-friendly text using OpenAI
    try:
        result = underwritingWorkflow.process_policy_document(
            s3_url=s3_url,
            policy_type=policy_type,
            bank_id=bank_id
        )
        return jsonify(result)
    except Exception as e:
        return jsonify({'error': str(e), 'status': 'failed'}), 500

@app.route(ROUTE + '/list_generated_rules', methods=['GET'])
def list_generated_rules():
    """List all generated rule files - DEPRECATED

    Note: This endpoint is deprecated as rules are no longer persisted locally.
    Rules are now uploaded directly to S3 and deployed to Drools KIE Server.
    Use S3 API to list generated rules from S3 bucket.
    """
    return jsonify({
        'rules': [],
        'count': 0,
        'message': 'Rules are no longer stored locally. Check S3 bucket for generated rules.'
    })

@app.route(ROUTE + '/get_rule_content', methods=['GET'])
def get_rule_content():
    """Get content of a generated rule file - DEPRECATED

    Note: This endpoint is deprecated as rules are no longer persisted locally.
    Use S3 API to retrieve rule content from S3 bucket.
    """
    filename = request.args.get('filename')
    if not filename:
        return jsonify({'error': 'filename parameter is required'}), 400

    return jsonify({
        'error': 'Rules are no longer stored locally. Retrieve from S3 bucket instead.'
    }), 404

@app.route(ROUTE + '/drools_containers', methods=['GET'])
def drools_containers():
    """List Drools KIE Server containers"""
    from DroolsDeploymentService import DroolsDeploymentService
    deployment = DroolsDeploymentService()
    result = deployment.list_containers()
    return jsonify(result)

@app.route(ROUTE + '/orchestrated_containers', methods=['GET'])
def orchestrated_containers():
    """List orchestrated Docker/K8s containers with health status"""
    from ContainerOrchestrator import get_orchestrator
    orchestrator = get_orchestrator()
    result = orchestrator.list_containers()
    return jsonify(result)

@app.route(ROUTE + '/drools_container_status', methods=['GET'])
def drools_container_status():
    """Get status of a specific Drools container"""
    container_id = request.args.get('container_id')
    if not container_id:
        return jsonify({'error': 'container_id parameter is required'}), 400

    from DroolsDeploymentService import DroolsDeploymentService
    deployment = DroolsDeploymentService()
    result = deployment.get_container_status(container_id)
    return jsonify(result)

@app.route(ROUTE + '/test_rules', methods=['POST'])
def test_rules():
    """
    Test deployed Drools rules with sample data

    Request body:
    {
        "container_id": "chase-insurance-underwriting-rules",
        "applicant": {
            "name": "John Doe",
            "age": 35,
            "occupation": "Engineer",
            "healthConditions": null
        },
        "policy": {
            "policyType": "Term Life",
            "coverageAmount": 500000,
            "term": 20
        }
    }

    Returns the Decision object with approval status, reason, and premium multiplier
    """
    data = request.get_json()

    if not data:
        return jsonify({'error': 'Request body is required'}), 400

    container_id = data.get('container_id')
    if not container_id:
        return jsonify({'error': 'container_id is required'}), 400

    applicant = data.get('applicant', {})
    policy = data.get('policy', {})

    try:
        # Execute rules via Drools KIE Server REST API
        import requests
        from requests.auth import HTTPBasicAuth

        drools_url = os.getenv('DROOLS_SERVER_URL', 'http://drools:8080/kie-server/services/rest/server')
        drools_user = os.getenv('DROOLS_USERNAME', 'kieserver')
        drools_password = os.getenv('DROOLS_PASSWORD', 'kieserver1!')

        # Build the request payload for Drools
        payload = {
            "lookup": None,
            "commands": [
                {
                    "insert": {
                        "object": {
                            "com.underwriting.rules.Applicant": applicant
                        },
                        "out-identifier": "applicant",
                        "return-object": True
                    }
                },
                {
                    "insert": {
                        "object": {
                            "com.underwriting.rules.Policy": policy
                        },
                        "out-identifier": "policy",
                        "return-object": True
                    }
                },
                {
                    "fire-all-rules": {
                        "max": -1,
                        "out-identifier": "fired"
                    }
                },
                {
                    "query": {
                        "name": "getDecision",
                        "out-identifier": "decision"
                    }
                }
            ]
        }

        # Alternative: Get all objects approach
        payload_alt = {
            "lookup": None,
            "commands": [
                {
                    "insert": {
                        "object": {
                            "com.underwriting.rules.Applicant": applicant
                        },
                        "out-identifier": "applicant",
                        "return-object": False
                    }
                },
                {
                    "insert": {
                        "object": {
                            "com.underwriting.rules.Policy": policy
                        },
                        "out-identifier": "policy",
                        "return-object": False
                    }
                },
                {
                    "fire-all-rules": {
                        "max": -1,
                        "out-identifier": "fired"
                    }
                },
                {
                    "get-objects": {
                        "out-identifier": "objects"
                    }
                }
            ]
        }

        print(f"Testing rules in container: {container_id}")
        print(f"Payload: {json.dumps(payload_alt, indent=2)}")

        response = requests.post(
            f"{drools_url}/containers/instances/{container_id}",
            auth=HTTPBasicAuth(drools_user, drools_password),
            headers={
                'Accept': 'application/json',
                'Content-Type': 'application/json'
            },
            json=payload_alt
        )

        print(f"Response status: {response.status_code}")
        print(f"Response body: {response.text}")

        if response.status_code == 200:
            result = response.json()

            # Extract Decision object from results
            decision = None
            if 'result' in result and 'execution-results' in result['result']:
                exec_results = result['result']['execution-results']
                if 'results' in exec_results:
                    for res in exec_results['results']:
                        if res.get('key') == 'objects':
                            objects = res.get('value', [])
                            # Objects is a list of dictionaries
                            if isinstance(objects, list):
                                for obj in objects:
                                    if 'com.underwriting.rules.Decision' in obj:
                                        decision = obj['com.underwriting.rules.Decision']
                                        break

            return jsonify({
                'status': 'success',
                'container_id': container_id,
                'decision': decision,
                'rules_fired': result.get('result', {}).get('execution-results', {}).get('results', []),
                'full_response': result
            })
        else:
            return jsonify({
                'status': 'error',
                'message': f'Drools execution failed with status {response.status_code}',
                'response': response.text
            }), response.status_code

    except Exception as e:
        print(f"Error testing rules: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({
            'status': 'error',
            'message': str(e)
        }), 500

# Cache management endpoints
@app.route(ROUTE + '/cache/status', methods=['GET'])
def get_cache_status():
    """
    Get cache statistics and list of cached documents

    Returns:
        JSON with cache directory, document count, and list of cached documents
    """
    try:
        cache = get_rule_cache()
        stats = cache.get_cache_stats()
        cached_docs = cache.list_cached_documents()

        return jsonify({
            "status": "success",
            "cache_stats": stats,
            "cached_documents": cached_docs
        })
    except Exception as e:
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500

@app.route(ROUTE + '/cache/clear', methods=['POST'])
def clear_cache():
    """
    Clear rule cache (specific document or all)

    Request body (optional):
        {
            "document_hash": "abc123..."  // Optional: clear specific document only
        }

    Returns:
        JSON with status and message
    """
    try:
        data = request.get_json() or {}
        document_hash = data.get('document_hash')

        cache = get_rule_cache()
        cache.clear_cache(document_hash)

        if document_hash:
            message = f"Cache cleared for document: {document_hash[:16]}..."
        else:
            message = "All cache cleared successfully"

        return jsonify({
            "status": "success",
            "message": message
        })
    except Exception as e:
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500

@app.route(ROUTE + '/cache/get', methods=['GET'])
def get_cached_rules():
    """
    Get cached rules for a specific document hash

    Query parameters:
        document_hash: SHA-256 hash of the document

    Returns:
        JSON with cached rule data or 404 if not found
    """
    try:
        document_hash = request.args.get('document_hash')
        if not document_hash:
            return jsonify({
                "status": "error",
                "message": "document_hash parameter required"
            }), 400

        cache = get_rule_cache()
        cached_result = cache.get_cached_rules(document_hash)

        if cached_result:
            return jsonify({
                "status": "success",
                "cached": True,
                "data": cached_result
            })
        else:
            return jsonify({
                "status": "success",
                "cached": False,
                "message": f"No cached rules found for {document_hash[:16]}..."
            }), 404
    except Exception as e:
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500

# ============================================================================
# CUSTOMER-FACING API ENDPOINTS (Database-backed)
# ============================================================================

@app.route(ROUTE + '/api/v1/banks', methods=['GET'])
def list_banks():
    """List all available banks"""
    try:
        banks = db_service.list_banks(active_only=True)
        return jsonify({
            "status": "success",
            "banks": [{
                "bank_id": bank['bank_id'],
                "bank_name": bank['bank_name'],
                "description": bank['description']
            } for bank in banks]
        })
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route(ROUTE + '/api/v1/banks/<bank_id>/policies', methods=['GET'])
def list_bank_policies(bank_id):
    """List all available policy types for a specific bank"""
    try:
        # Get active containers for this bank
        containers = db_service.list_containers(bank_id=bank_id, active_only=True)

        # Get unique policy type IDs
        policy_type_ids = list(set([c['policy_type_id'] for c in containers]))

        # Get all policy types and filter by the ones available for this bank
        all_policy_types = db_service.list_policy_types(active_only=True)

        # Filter to only include policy types that have containers for this bank
        policies = [
            {
                "policy_type_id": pt['policy_type_id'],
                "policy_name": pt['policy_name'],
                "description": pt['description'],
                "category": pt['category']
            }
            for pt in all_policy_types
            if pt['policy_type_id'] in policy_type_ids
        ]

        return jsonify({
            "status": "success",
            "bank_id": bank_id,
            "policies": policies
        })
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route(ROUTE + '/api/v1/policies', methods=['GET'])
def query_policies():
    """Query for available policy containers"""
    try:
        bank_id = request.args.get('bank_id')
        policy_type = request.args.get('policy_type')

        if not bank_id or not policy_type:
            return jsonify({
                "error": "Both bank_id and policy_type query parameters are required"
            }), 400

        # Get active container for this bank+policy combination
        container = db_service.get_active_container(bank_id, policy_type)

        if not container:
            return jsonify({
                "status": "not_found",
                "message": f"No active container found for bank '{bank_id}' and policy type '{policy_type}'"
            }), 404

        return jsonify({
            "status": "success",
            "container": {
                "container_id": container['container_id'],
                "bank_id": container['bank_id'],
                "policy_type_id": container['policy_type_id'],
                "endpoint": container['endpoint'],
                "status": container['status'],
                "health_status": container['health_status'],
                "deployed_at": container['deployed_at']
            }
        })
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route(ROUTE + '/api/v1/evaluate-policy', methods=['POST'])
def evaluate_policy():
    """
    Evaluate a policy application using deployed rule engine

    This is the main customer-facing endpoint for evaluating applications
    """
    try:
        data = request.get_json()

        if not data:
            return jsonify({'error': 'JSON body is required'}), 400

        # Validate required fields
        if 'bank_id' not in data:
            return jsonify({'error': 'bank_id is required'}), 400

        if 'policy_type' not in data:
            return jsonify({'error': 'policy_type is required'}), 400

        if 'applicant' not in data:
            return jsonify({'error': 'applicant data is required'}), 400

        bank_id = data['bank_id']
        policy_type = data['policy_type']
        applicant = data['applicant']
        policy_data = data.get('policy', {})

        # Get the active container for this bank+policy
        container = db_service.get_active_container(bank_id, policy_type)

        if not container:
            return jsonify({
                "status": "error",
                "message": f"No active rules deployed for bank '{bank_id}' and policy type '{policy_type}'. Please deploy rules first."
            }), 404

        print(f"DEBUG: Container retrieved from DB - ID: {container['container_id']}, Status: {container['status']}, Health: {container['health_status']}")

        # If container appears unhealthy, try to get fresh endpoint (which triggers health check)
        if container['status'] != 'running' or container['health_status'] != 'healthy':
            print(f"DEBUG: Container appears unhealthy, running fresh health check via orchestrator...")
            from ContainerOrchestrator import ContainerOrchestrator
            orchestrator = ContainerOrchestrator()
            fresh_endpoint = orchestrator.get_container_endpoint(container['container_id'])

            if fresh_endpoint:
                print(f"DEBUG: Health check PASSED! Endpoint: {fresh_endpoint}")
                # Refresh container data from database after health check
                container = db_service.get_active_container(bank_id, policy_type)
                print(f"DEBUG: Refreshed container - Status: {container['status']}, Health: {container['health_status']}")
            else:
                print(f"DEBUG: Health check FAILED - container not responsive")
                return jsonify({
                    "status": "error",
                    "message": f"Rule container is not healthy. Status: {container['status']}, Health: {container['health_status']}"
                }), 503

        # Prepare request for Drools
        container_path = f"/kie-server/services/rest/server/containers/instances/{container['container_id']}"

        # Build the payload for Drools
        request_payload = {
            "applicant": applicant,
            "policy": policy_data
        }

        import time
        start_time = time.time()

        # Invoke the rule engine
        try:
            decision = droolsService.invokeDecisionService(container_path, request_payload)
            execution_time = int((time.time() - start_time) * 1000)  # ms

            # Log the request to database for analytics
            db_service.log_request({
                'container_id': container['id'],
                'bank_id': bank_id,
                'policy_type_id': policy_type,
                'endpoint': container_path,
                'http_method': 'POST',
                'request_payload': request_payload,
                'response_payload': decision,
                'execution_time_ms': execution_time,
                'status': 'success',
                'status_code': 200
            })

            return jsonify({
                "status": "success",
                "bank_id": bank_id,
                "policy_type": policy_type,
                "container_id": container['container_id'],
                "decision": decision,
                "execution_time_ms": execution_time
            })

        except Exception as rule_error:
            execution_time = int((time.time() - start_time) * 1000)

            # Log the error
            db_service.log_request({
                'container_id': container['id'],
                'bank_id': bank_id,
                'policy_type_id': policy_type,
                'endpoint': container_path,
                'http_method': 'POST',
                'request_payload': request_payload,
                'execution_time_ms': execution_time,
                'status': 'error',
                'status_code': 500,
                'error_message': str(rule_error)
            })

            return jsonify({
                "status": "error",
                "message": f"Error executing rules: {str(rule_error)}"
            }), 500

    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route(ROUTE + '/api/v1/deployments', methods=['GET'])
def list_deployments():
    """List all rule deployments (admin endpoint)"""
    try:
        bank_id = request.args.get('bank_id')
        policy_type = request.args.get('policy_type')
        status = request.args.get('status')
        active_only = request.args.get('active_only', 'false').lower() == 'true'

        containers = db_service.list_containers(
            bank_id=bank_id,
            policy_type_id=policy_type,
            status=status,
            active_only=active_only
        )

        return jsonify({
            "status": "success",
            "total": len(containers),
            "deployments": [{
                "id": c['id'],
                "container_id": c['container_id'],
                "bank_id": c['bank_id'],
                "policy_type_id": c['policy_type_id'],
                "endpoint": c['endpoint'],
                "status": c['status'],
                "health_status": c['health_status'],
                "platform": c['platform'],
                "version": c['version'],
                "is_active": c['is_active'],
                "deployed_at": c['deployed_at'],
                "s3_jar_url": c['s3_jar_url'],
                "s3_drl_url": c['s3_drl_url'],
                "s3_excel_url": c['s3_excel_url']
            } for c in containers]
        })
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route(ROUTE + '/api/v1/deployments/<int:deployment_id>', methods=['GET'])
def get_deployment(deployment_id):
    """Get details of a specific deployment"""
    try:
        container = db_service.get_container_by_db_id(deployment_id)

        if not container:
            return jsonify({
                "status": "not_found",
                "message": f"Deployment {deployment_id} not found"
            }), 404

        # Get statistics
        stats = db_service.get_container_stats(container['container_id'])

        return jsonify({
            "status": "success",
            "deployment": {
                "id": container['id'],
                "container_id": container['container_id'],
                "bank_id": container['bank_id'],
                "policy_type_id": container['policy_type_id'],
                "endpoint": container['endpoint'],
                "status": container['status'],
                "health_status": container['health_status'],
                "platform": container['platform'],
                "port": container['port'],
                "version": container['version'],
                "is_active": container['is_active'],
                "deployed_at": container['deployed_at'],
                "document_hash": container['document_hash'],
                "s3_policy_url": container['s3_policy_url'],
                "s3_jar_url": container['s3_jar_url'],
                "s3_drl_url": container['s3_drl_url'],
                "s3_excel_url": container['s3_excel_url']
            },
            "statistics": stats
        })
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route(ROUTE + '/api/v1/discovery', methods=['GET'])
def service_discovery():
    """Service discovery endpoint - list all banks with their available policies"""
    try:
        result = db_service.get_banks_with_policies()
        return jsonify({
            "status": "success",
            "services": result
        })
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route(ROUTE + '/api/v1/extracted-rules', methods=['GET'])
def get_extracted_rules():
    """Get extracted rules for a specific bank and policy type"""
    try:
        bank_id = request.args.get('bank_id')
        policy_type = request.args.get('policy_type')

        if not bank_id or not policy_type:
            return jsonify({
                "status": "error",
                "message": "Both bank_id and policy_type query parameters are required"
            }), 400

        # Fetch extracted rules from database
        rules = db_service.get_extracted_rules(bank_id, policy_type, active_only=True)

        return jsonify({
            "status": "success",
            "bank_id": bank_id,
            "policy_type": policy_type,
            "rule_count": len(rules),
            "rules": rules
        })
    except Exception as e:
        logger.error(f"Error fetching extracted rules: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route(ROUTE + '/api/v1/health', methods=['GET'])
def health_check():
    """Health check endpoint"""
    try:
        db_healthy = db_service.health_check()
        drools_healthy = droolsService.isConnected

        return jsonify({
            "status": "healthy" if (db_healthy and drools_healthy) else "unhealthy",
            "database": "connected" if db_healthy else "disconnected",
            "drools": "connected" if drools_healthy else "disconnected"
        }), 200 if (db_healthy and drools_healthy) else 503
    except Exception as e:
        return jsonify({
            "status": "unhealthy",
            "error": str(e)
        }), 503

# File upload endpoint
@app.route(ROUTE + '/upload_file', methods=['POST'])
def upload_file():
    """
    Upload a file to AWS S3 bucket
    
    Accepts multipart/form-data with a file field.
    Files are stored in S3 with organized folder structure: uploads/YYYY-MM-DD/filename_timestamp.ext
    
    Returns:
        - 200: File uploaded successfully with S3 URL
        - 400: Missing file or invalid request
        - 500: Upload failed (S3 error, network error, etc.)
    """
    try:
        # Check if file is present in request
        if 'file' not in request.files:
            return jsonify({
                'status': 'error',
                'message': 'No file provided. Please include a file in the "file" field.',
                'error_code': 'MISSING_FILE'
            }), 400
        
        file = request.files['file']
        
        # Check if file is actually selected
        if file.filename == '':
            return jsonify({
                'status': 'error',
                'message': 'No file selected. Please select a file to upload.',
                'error_code': 'EMPTY_FILENAME'
            }), 400
        
        # Get optional parameters
        folder = request.form.get('folder', 'uploads')  # Default folder: 'uploads'
        max_file_size = 100 * 1024 * 1024  # 100 MB limit
        
        # Validate folder name (prevent path traversal)
        if '..' in folder or '/' in folder or '\\' in folder:
            return jsonify({
                'status': 'error',
                'message': 'Invalid folder name. Folder cannot contain path separators or ".."',
                'error_code': 'INVALID_FOLDER'
            }), 400
        
        # Read file content
        file_content = file.read()
        file_size = len(file_content)
        
        # Validate file size
        if file_size == 0:
            return jsonify({
                'status': 'error',
                'message': 'File is empty. Please upload a non-empty file.',
                'error_code': 'EMPTY_FILE'
            }), 400
        
        if file_size > max_file_size:
            return jsonify({
                'status': 'error',
                'message': f'File size ({file_size} bytes) exceeds maximum allowed size ({max_file_size} bytes)',
                'error_code': 'FILE_TOO_LARGE',
                'file_size': file_size,
                'max_size': max_file_size
            }), 400
        
        # Get original filename
        original_filename = secure_filename(file.filename)
        
        # Upload to S3
        upload_result = s3Service.upload_file_to_s3(
            file_content=file_content,
            filename=original_filename,
            folder=folder
        )
        
        # Check upload result
        if upload_result.get('status') == 'error':
            return jsonify({
                'status': 'error',
                'message': upload_result.get('message', 'Upload failed'),
                'error': upload_result.get('error', 'Unknown error'),
                'error_code': upload_result.get('error_code', 'UPLOAD_FAILED')
            }), 500
        
        # Return success response
        return jsonify({
            'status': 'success',
            'message': 'File uploaded successfully to S3',
            'data': {
                's3_url': upload_result.get('s3_url'),
                's3_key': upload_result.get('s3_key'),
                'bucket': upload_result.get('bucket'),
                'filename': upload_result.get('filename'),
                'original_filename': upload_result.get('original_filename'),
                'folder': upload_result.get('folder'),
                'file_size': upload_result.get('file_size'),
                'content_type': upload_result.get('content_type')
            }
        }), 200
        
    except Exception as e:
        print(f"Error in upload_file endpoint: {str(e)}")
        return jsonify({
            'status': 'error',
            'message': f'Internal server error: {str(e)}',
            'error_code': 'INTERNAL_ERROR'
        }), 500

# Swagger documentation endpoints
@app.route(ROUTE + '/swagger.yaml', methods=['GET'])
def get_swagger_yaml():
    """Serve Swagger YAML specification"""
    return send_from_directory('.', 'swagger.yaml')

@app.route(ROUTE + '/docs', methods=['GET'])
def swagger_ui():
    """Serve Swagger UI HTML page"""
    html = """
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Underwriting API Documentation</title>
        <link rel="stylesheet" type="text/css" href="https://unpkg.com/swagger-ui-dist@5.10.3/swagger-ui.css">
        <style>
            body { margin: 0; padding: 0; }
        </style>
    </head>
    <body>
        <div id="swagger-ui"></div>
        <script src="https://unpkg.com/swagger-ui-dist@5.10.3/swagger-ui-bundle.js"></script>
        <script src="https://unpkg.com/swagger-ui-dist@5.10.3/swagger-ui-standalone-preset.js"></script>
        <script>
            window.onload = function() {
                const ui = SwaggerUIBundle({
                    url: '/rule-agent/swagger.yaml',
                    dom_id: '#swagger-ui',
                    deepLinking: true,
                    presets: [
                        SwaggerUIBundle.presets.apis,
                        SwaggerUIStandalonePreset
                    ],
                    plugins: [
                        SwaggerUIBundle.plugins.DownloadUrl
                    ],
                    layout: "StandaloneLayout"
                });
                window.ui = ui;
            };
        </script>
    </body>
    </html>
    """
    return html

print ('Running chat service')

if __name__ == '__main__':
    app.run(debug=True)
