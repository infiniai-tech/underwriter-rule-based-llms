-- Sample Data: Insert sample extracted rules for testing
-- Purpose: Provide test data for extracted_rules table
-- Date: 2025-11-10
-- Note: Run this AFTER the main migration script

-- Insert sample extracted rules for Chase Life Insurance policy
INSERT INTO extracted_rules (bank_id, policy_type_id, rule_name, requirement, category, source_document, document_hash, is_active)
VALUES
    -- Age Requirements
    ('chase', 'insurance', 'Minimum Age Requirement', 'Applicant must be at least 18 years old (MANDATORY - Applications under 18 are AUTOMATICALLY REJECTED)', 'Age Requirements', 'sample_life_insurance_policy.txt', 'sample_hash_001', TRUE),
    ('chase', 'insurance', 'Maximum Age Requirement', 'Applicant must be 65 years old or younger (MANDATORY - Applications over 65 are AUTOMATICALLY REJECTED)', 'Age Requirements', 'sample_life_insurance_policy.txt', 'sample_hash_001', TRUE),
    ('chase', 'insurance', 'Preferred Age Range', 'Ages 25-55 years qualify for best rates', 'Age Requirements', 'sample_life_insurance_policy.txt', 'sample_hash_001', TRUE),

    -- Credit Score Requirements
    ('chase', 'insurance', 'Minimum Credit Score', 'Credit score must be at least 600 (MANDATORY - Applications under 600 are AUTOMATICALLY REJECTED)', 'Credit Score Requirements', 'sample_life_insurance_policy.txt', 'sample_hash_001', TRUE),
    ('chase', 'insurance', 'Preferred Credit Score', 'Credit score of 700+ qualifies for standard rates', 'Credit Score Requirements', 'sample_life_insurance_policy.txt', 'sample_hash_001', TRUE),
    ('chase', 'insurance', 'Excellent Credit Score', 'Credit score of 750+ qualifies for discounted rates', 'Credit Score Requirements', 'sample_life_insurance_policy.txt', 'sample_hash_001', TRUE),

    -- Income Requirements
    ('chase', 'insurance', 'Minimum Annual Income', 'Annual income must be at least $25,000', 'Income Requirements', 'sample_life_insurance_policy.txt', 'sample_hash_001', TRUE),
    ('chase', 'insurance', 'Coverage to Income Ratio', 'Coverage cannot exceed 10x annual income', 'Income Requirements', 'sample_life_insurance_policy.txt', 'sample_hash_001', TRUE),
    ('chase', 'insurance', 'Income Verification', 'Income verification required for coverage over $500,000', 'Income Requirements', 'sample_life_insurance_policy.txt', 'sample_hash_001', TRUE),

    -- Health Requirements
    ('chase', 'insurance', 'Health Status Declaration', 'Health status must be declared: excellent, good, fair, or poor', 'Health Requirements', 'sample_life_insurance_policy.txt', 'sample_hash_001', TRUE),
    ('chase', 'insurance', 'Poor Health Rejection', 'Poor health status: AUTOMATICALLY REJECTED', 'Health Requirements', 'sample_life_insurance_policy.txt', 'sample_hash_001', TRUE),
    ('chase', 'insurance', 'Fair Health Review', 'Fair health status: Manual underwriting review required', 'Health Requirements', 'sample_life_insurance_policy.txt', 'sample_hash_001', TRUE),
    ('chase', 'insurance', 'Medical Examination', 'Medical examination required for coverage over $500,000', 'Health Requirements', 'sample_life_insurance_policy.txt', 'sample_hash_001', TRUE),

    -- Automatic Rejection Criteria
    ('chase', 'insurance', 'Age Rejection', 'Age under 18 or over 65 years: AUTOMATIC REJECTION', 'Automatic Rejection Criteria', 'sample_life_insurance_policy.txt', 'sample_hash_001', TRUE),
    ('chase', 'insurance', 'Credit Score Rejection', 'Credit score below 600: AUTOMATIC REJECTION', 'Automatic Rejection Criteria', 'sample_life_insurance_policy.txt', 'sample_hash_001', TRUE),
    ('chase', 'insurance', 'Poor Health Rejection', 'Health status declared as "poor": AUTOMATIC REJECTION', 'Automatic Rejection Criteria', 'sample_life_insurance_policy.txt', 'sample_hash_001', TRUE),
    ('chase', 'insurance', 'Low Income Rejection', 'Annual income below $25,000: AUTOMATIC REJECTION', 'Automatic Rejection Criteria', 'sample_life_insurance_policy.txt', 'sample_hash_001', TRUE),
    ('chase', 'insurance', 'Coverage Ratio Rejection', 'Requested coverage exceeds 10x annual income: AUTOMATIC REJECTION', 'Automatic Rejection Criteria', 'sample_life_insurance_policy.txt', 'sample_hash_001', TRUE),
    ('chase', 'insurance', 'Smoking and Age Rejection', 'Smoking status combined with age over 60 and coverage over $300,000: AUTOMATIC REJECTION', 'Automatic Rejection Criteria', 'sample_life_insurance_policy.txt', 'sample_hash_001', TRUE),
    ('chase', 'insurance', 'DUI Rejection', 'DUI conviction within the past 5 years: AUTOMATIC REJECTION', 'Automatic Rejection Criteria', 'sample_life_insurance_policy.txt', 'sample_hash_001', TRUE),
    ('chase', 'insurance', 'Hazardous Occupation Rejection', 'Hazardous occupation without additional riders: AUTOMATIC REJECTION', 'Automatic Rejection Criteria', 'sample_life_insurance_policy.txt', 'sample_hash_001', TRUE),

    -- Coverage Tiers
    ('chase', 'insurance', 'Tier 1 Coverage Range', 'Standard Coverage: $50,000 - $100,000', 'Coverage Tiers', 'sample_life_insurance_policy.txt', 'sample_hash_001', TRUE),
    ('chase', 'insurance', 'Tier 1 Auto Approval', 'Ages 18-55, credit score 600+, good/excellent health: AUTOMATIC APPROVAL', 'Coverage Tiers', 'sample_life_insurance_policy.txt', 'sample_hash_001', TRUE),
    ('chase', 'insurance', 'Tier 2 Coverage Range', 'Enhanced Coverage: $100,001 - $300,000', 'Coverage Tiers', 'sample_life_insurance_policy.txt', 'sample_hash_001', TRUE),
    ('chase', 'insurance', 'Tier 2 Auto Approval', 'Ages 18-50, credit score 700+, good/excellent health, non-smoker: AUTOMATIC APPROVAL', 'Coverage Tiers', 'sample_life_insurance_policy.txt', 'sample_hash_001', TRUE),
    ('chase', 'insurance', 'Tier 3 Coverage Range', 'Premium Coverage: $300,001 - $500,000', 'Coverage Tiers', 'sample_life_insurance_policy.txt', 'sample_hash_001', TRUE),
    ('chase', 'insurance', 'Tier 3 Auto Approval', 'Ages 18-45, credit score 750+, excellent health, non-smoker: AUTOMATIC APPROVAL', 'Coverage Tiers', 'sample_life_insurance_policy.txt', 'sample_hash_001', TRUE),
    ('chase', 'insurance', 'Tier 4 Coverage Range', 'High-Value Coverage: $500,001 - $1,000,000', 'Coverage Tiers', 'sample_life_insurance_policy.txt', 'sample_hash_001', TRUE),
    ('chase', 'insurance', 'Tier 4 Manual Review', 'ALL applications for $500,001+ coverage: REQUIRES MANUAL UNDERWRITING REVIEW', 'Coverage Tiers', 'sample_life_insurance_policy.txt', 'sample_hash_001', TRUE)
ON CONFLICT DO NOTHING;

-- Display success message with count
DO $$
DECLARE
    rule_count INTEGER;
BEGIN
    SELECT COUNT(*) INTO rule_count FROM extracted_rules WHERE bank_id = 'chase' AND policy_type_id = 'insurance';
    RAISE NOTICE 'Sample data inserted successfully!';
    RAISE NOTICE 'Total rules for chase/insurance: %', rule_count;
END $$;
