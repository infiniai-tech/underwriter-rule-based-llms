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
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import JsonOutputParser
from typing import List, Dict
import json

class PolicyAnalyzerAgent:
    """
    Analyzes policy documents and generates queries for Textract extraction
    """

    def __init__(self, llm):
        self.llm = llm

        self.analysis_prompt = ChatPromptTemplate.from_messages([
            ("system", """You are an expert insurance policy analyst specializing in underwriting rules.

Your task is to analyze policy document text and identify key underwriting criteria that need to be extracted.

Focus on extracting:
- Coverage limits and amounts
- Age restrictions and requirements
- Eligibility criteria
- Premium calculation factors
- Excluded conditions or situations
- Risk assessment criteria
- Required documentation
- Approval thresholds

Generate specific, targeted queries that AWS Textract can use to extract precise data from the document.

Return a JSON object with this structure:
{{
    "queries": [
        "What is the maximum coverage amount?",
        "What is the minimum age requirement for applicants?",
        "What is the maximum age limit for applicants?"
    ],
    "key_sections": [
        "Coverage Limits",
        "Eligibility Requirements"
    ],
    "rule_categories": [
        "age_restrictions",
        "coverage_limits"
    ]
}}

Make queries specific and actionable. Each query should extract a concrete value or fact."""),
            ("user", "Policy document text:\n\n{document_text}")
        ])

        self.chain = self.analysis_prompt | self.llm | JsonOutputParser()

    def analyze_policy(self, document_text: str) -> Dict:
        """
        Analyze policy document and generate Textract queries

        :param document_text: Text extracted from PDF (via PyPDF or basic parsing)
        :return: Dictionary with queries, key_sections, and rule_categories
        """
        try:
            # Truncate document if too long (keep first 15000 chars for analysis)
            if len(document_text) > 15000:
                print(f"Document is long ({len(document_text)} chars), truncating to 15000 for analysis")
                document_text = document_text[:15000]

            result = self.chain.invoke({"document_text": document_text})

            # Ensure result has expected structure
            if "queries" not in result:
                result["queries"] = []

            if "key_sections" not in result:
                result["key_sections"] = []

            if "rule_categories" not in result:
                result["rule_categories"] = []

            print(f"Policy analysis complete: {len(result['queries'])} queries generated")
            return result

        except Exception as e:
            print(f"Error analyzing policy: {e}")
            # Return default structure with error
            return {
                "queries": [
                    "What is the maximum coverage amount?",
                    "What are the age requirements?",
                    "What are the eligibility criteria?"
                ],
                "key_sections": [],
                "rule_categories": [],
                "error": str(e)
            }

    def generate_template_queries(self, policy_type: str = "general") -> List[str]:
        """
        Generate template queries for common policy types

        :param policy_type: Type of policy (general, life, health, auto, property)
        :return: List of template queries
        """
        templates = {
            "general": [
                "What is the maximum coverage amount?",
                "What is the minimum coverage amount?",
                "What is the age limit for applicants?",
                "What are the excluded conditions?",
                "What is the deductible amount?"
            ],
            "life": [
                "What is the maximum life insurance coverage amount?",
                "What is the minimum age for life insurance applicants?",
                "What is the maximum age for life insurance applicants?",
                "What pre-existing conditions are excluded?",
                "What is the waiting period for coverage?",
                "What are the premium payment options?"
            ],
            "health": [
                "What is the maximum health insurance coverage?",
                "What is the annual deductible?",
                "What is the out-of-pocket maximum?",
                "What pre-existing conditions are covered?",
                "What is the waiting period for major medical procedures?",
                "What preventive care services are covered?"
            ],
            "auto": [
                "What is the minimum liability coverage required?",
                "What is the maximum coverage for collision damage?",
                "What is the age requirement for primary drivers?",
                "What is the deductible for comprehensive coverage?",
                "Are rental car expenses covered?"
            ],
            "property": [
                "What is the maximum property value covered?",
                "What natural disasters are covered?",
                "What is the deductible for property damage?",
                "Are earthquake and flood damages covered?",
                "What is the replacement cost coverage limit?"
            ]
        }

        return templates.get(policy_type.lower(), templates["general"])
