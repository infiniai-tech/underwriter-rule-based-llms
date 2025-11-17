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

"""
Test Case Generator for Underwriting Policies
Automatically generates comprehensive test cases using LLM based on policy documents and extracted rules.
"""

import json
import logging
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)


class TestCaseGenerator:
    """
    Generates test cases for policy evaluation using LLM analysis
    """

    def __init__(self, llm):
        """
        Initialize the test case generator

        Args:
            llm: Language model instance for test case generation
        """
        self.llm = llm

    def generate_test_cases(self,
                          policy_text: str,
                          extracted_rules: List[Dict[str, Any]] = None,
                          hierarchical_rules: List[Dict[str, Any]] = None,
                          policy_type: str = "insurance") -> List[Dict[str, Any]]:
        """
        Generate comprehensive test cases based on policy document and rules

        Args:
            policy_text: Full policy document text
            extracted_rules: List of extracted rules from DRL
            hierarchical_rules: List of hierarchical rules
            policy_type: Type of policy (insurance, loan, etc.)

        Returns:
            List of test case dictionaries
        """
        logger.info("Generating test cases using LLM...")

        # Build context from rules
        rules_context = self._build_rules_context(extracted_rules, hierarchical_rules)

        # Create the prompt for LLM
        prompt = self._create_test_generation_prompt(policy_text, rules_context, policy_type)

        # Get LLM response
        try:
            response = self.llm.invoke(prompt)
            response_text = response.content if hasattr(response, 'content') else str(response)

            # Parse JSON from response
            test_cases = self._parse_test_cases(response_text)

            logger.info(f"Generated {len(test_cases)} test cases")
            return test_cases

        except Exception as e:
            logger.error(f"Error generating test cases: {e}")
            # Return default test cases as fallback
            return self._generate_default_test_cases(policy_type)

    def _build_rules_context(self,
                            extracted_rules: List[Dict[str, Any]] = None,
                            hierarchical_rules: List[Dict[str, Any]] = None) -> str:
        """Build context string from extracted rules"""
        context = []

        if extracted_rules:
            context.append("## Extracted Rules:")
            for i, rule in enumerate(extracted_rules[:20], 1):  # Limit to 20 rules
                rule_text = f"{i}. {rule.get('rule_name', 'Unknown')}: {rule.get('requirement', '')}"
                context.append(rule_text)

        if hierarchical_rules:
            context.append("\n## Hierarchical Rules Structure:")
            for rule in hierarchical_rules[:10]:  # Limit to 10 top-level rules
                rule_text = f"- {rule.get('name', 'Unknown')}: {rule.get('expected', '')}"
                context.append(rule_text)

        return "\n".join(context) if context else "No specific rules provided"

    def _create_test_generation_prompt(self, policy_text: str, rules_context: str, policy_type: str) -> str:
        """Create the LLM prompt for test case generation"""
        return f"""You are a test case generator for {policy_type} underwriting policies.

Your task is to generate comprehensive test cases that cover various scenarios for policy evaluation.

# Policy Document:
{policy_text[:3000]}... (truncated for brevity)

# Extracted Rules:
{rules_context}

# Instructions:
Generate 5-10 diverse test cases covering:
1. **Positive Cases**: Ideal applicants who should be approved
2. **Negative Cases**: Applicants who should be rejected
3. **Boundary Cases**: Applicants at the edge of approval/rejection criteria
4. **Edge Cases**: Unusual or rare scenarios

For each test case, provide:
- test_case_name: Clear, descriptive name
- description: Detailed description of the scenario
- category: One of [positive, negative, boundary, edge_case]
- priority: 1 (high), 2 (medium), or 3 (low)
- applicant_data: JSON object with applicant details
- policy_data: JSON object with policy details
- expected_decision: "approved" or "rejected"
- expected_reasons: Array of reasons for the decision
- expected_risk_category: Risk score 1-5 (1=lowest risk, 5=highest risk)

# Output Format:
Return ONLY a valid JSON array of test cases. Example:

```json
[
  {{
    "test_case_name": "Ideal Applicant - Mid-Age, Good Health",
    "description": "35-year-old non-smoker with excellent health, high income, and good credit score",
    "category": "positive",
    "priority": 1,
    "applicant_data": {{
      "age": 35,
      "annualIncome": 75000,
      "creditScore": 720,
      "healthConditions": "good",
      "smoker": false
    }},
    "policy_data": {{
      "coverageAmount": 500000,
      "termYears": 20,
      "type": "term_life"
    }},
    "expected_decision": "approved",
    "expected_reasons": ["Meets all eligibility criteria", "Low risk profile"],
    "expected_risk_category": 2
  }},
  {{
    "test_case_name": "High Risk - Elderly Smoker",
    "description": "70-year-old smoker with pre-existing health conditions",
    "category": "negative",
    "priority": 1,
    "applicant_data": {{
      "age": 70,
      "annualIncome": 45000,
      "creditScore": 650,
      "healthConditions": "fair",
      "smoker": true
    }},
    "policy_data": {{
      "coverageAmount": 1000000,
      "termYears": 30,
      "type": "term_life"
    }},
    "expected_decision": "rejected",
    "expected_reasons": ["Age exceeds maximum limit", "High risk due to smoking", "Pre-existing health conditions"],
    "expected_risk_category": 5
  }}
]
```

Generate the test cases now:"""

    def _parse_test_cases(self, response_text: str) -> List[Dict[str, Any]]:
        """Parse test cases from LLM response"""
        try:
            # Try to extract JSON from markdown code blocks
            if "```json" in response_text:
                json_start = response_text.find("```json") + 7
                json_end = response_text.find("```", json_start)
                json_text = response_text[json_start:json_end].strip()
            elif "```" in response_text:
                json_start = response_text.find("```") + 3
                json_end = response_text.find("```", json_start)
                json_text = response_text[json_start:json_end].strip()
            else:
                # Try to find JSON array directly
                json_start = response_text.find("[")
                json_end = response_text.rfind("]") + 1
                json_text = response_text[json_start:json_end].strip()

            # Parse JSON
            test_cases = json.loads(json_text)

            # Add metadata
            for tc in test_cases:
                tc['is_auto_generated'] = True
                tc['generation_method'] = 'llm'

            return test_cases

        except Exception as e:
            logger.error(f"Error parsing test cases JSON: {e}")
            logger.debug(f"Response text: {response_text[:500]}")
            return []

    def _generate_default_test_cases(self, policy_type: str) -> List[Dict[str, Any]]:
        """Generate default test cases when LLM fails"""
        logger.info("Generating default test cases as fallback...")

        if policy_type == "insurance":
            return [
                {
                    "test_case_name": "Ideal Applicant - Mid-Age, Good Health",
                    "description": "Standard approval case for healthy middle-aged applicant",
                    "category": "positive",
                    "priority": 1,
                    "applicant_data": {
                        "age": 35,
                        "annualIncome": 75000,
                        "creditScore": 720,
                        "healthConditions": "good",
                        "smoker": False
                    },
                    "policy_data": {
                        "coverageAmount": 500000,
                        "termYears": 20,
                        "type": "term_life"
                    },
                    "expected_decision": "approved",
                    "expected_reasons": ["Meets all eligibility criteria"],
                    "expected_risk_category": 2,
                    "is_auto_generated": True,
                    "generation_method": "template"
                },
                {
                    "test_case_name": "Young Professional - High Income",
                    "description": "Young applicant with excellent income and credit",
                    "category": "positive",
                    "priority": 2,
                    "applicant_data": {
                        "age": 28,
                        "annualIncome": 95000,
                        "creditScore": 780,
                        "healthConditions": "excellent",
                        "smoker": False
                    },
                    "policy_data": {
                        "coverageAmount": 750000,
                        "termYears": 30,
                        "type": "term_life"
                    },
                    "expected_decision": "approved",
                    "expected_reasons": ["Excellent health profile", "High income to coverage ratio"],
                    "expected_risk_category": 1,
                    "is_auto_generated": True,
                    "generation_method": "template"
                },
                {
                    "test_case_name": "Boundary - Minimum Age",
                    "description": "Applicant at minimum age threshold",
                    "category": "boundary",
                    "priority": 1,
                    "applicant_data": {
                        "age": 18,
                        "annualIncome": 35000,
                        "creditScore": 680,
                        "healthConditions": "good",
                        "smoker": False
                    },
                    "policy_data": {
                        "coverageAmount": 250000,
                        "termYears": 20,
                        "type": "term_life"
                    },
                    "expected_decision": "approved",
                    "expected_reasons": ["Meets minimum age requirement"],
                    "expected_risk_category": 3,
                    "is_auto_generated": True,
                    "generation_method": "template"
                },
                {
                    "test_case_name": "Negative - High Risk Smoker",
                    "description": "Smoker with fair health conditions",
                    "category": "negative",
                    "priority": 1,
                    "applicant_data": {
                        "age": 55,
                        "annualIncome": 60000,
                        "creditScore": 640,
                        "healthConditions": "fair",
                        "smoker": True
                    },
                    "policy_data": {
                        "coverageAmount": 1000000,
                        "termYears": 25,
                        "type": "term_life"
                    },
                    "expected_decision": "rejected",
                    "expected_reasons": ["High risk due to smoking", "Health conditions below threshold"],
                    "expected_risk_category": 5,
                    "is_auto_generated": True,
                    "generation_method": "template"
                },
                {
                    "test_case_name": "Edge Case - Elderly with Excellent Health",
                    "description": "Elderly applicant but with excellent health metrics",
                    "category": "edge_case",
                    "priority": 2,
                    "applicant_data": {
                        "age": 64,
                        "annualIncome": 80000,
                        "creditScore": 750,
                        "healthConditions": "excellent",
                        "smoker": False
                    },
                    "policy_data": {
                        "coverageAmount": 400000,
                        "termYears": 15,
                        "type": "term_life"
                    },
                    "expected_decision": "approved",
                    "expected_reasons": ["Excellent health compensates for age"],
                    "expected_risk_category": 3,
                    "is_auto_generated": True,
                    "generation_method": "template"
                }
            ]
        else:
            # Generic template for other policy types
            return [
                {
                    "test_case_name": f"Standard {policy_type.title()} Approval",
                    "description": f"Standard approval case for {policy_type} policy",
                    "category": "positive",
                    "priority": 1,
                    "applicant_data": {
                        "age": 35,
                        "annualIncome": 75000,
                        "creditScore": 720
                    },
                    "policy_data": {},
                    "expected_decision": "approved",
                    "expected_reasons": ["Meets standard criteria"],
                    "expected_risk_category": 2,
                    "is_auto_generated": True,
                    "generation_method": "template"
                }
            ]
