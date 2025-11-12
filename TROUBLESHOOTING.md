# Troubleshooting Guide

## Common Issues and Solutions

### Issue 1: Drools Compilation Error - "Unable to resolve method"

**Symptom:**
```
Failed to create container: Error while creating KieBase
Unable to Analyse Expression loanType == "personal":
[Error: unable to resolve method using strict-mode: com.underwriting.rules.Applicant.loanType()]
```

**Root Cause:**
The LLM-generated DRL rules reference fields (like `loanType`) that don't exist in the `declare` statements at the top of the DRL file.

**Why This Happens:**
- The LLM sometimes generates rules that use fields not declared in the type definitions
- This is an LLM consistency issue - it needs to declare all fields before using them in rules

**Solution 1: Improved LLM Prompt (✅ FIXED)**

We've updated the prompts in `RuleGeneratorAgent.py` to emphasize:
- **CRITICAL**: Every field referenced in rules MUST be declared in the type definition
- **CRITICAL**: Decide ALL fields needed first, then add them to declare statements
- **CRITICAL**: For hierarchical rules, use the SAME declare statements in all 3 levels

The updated prompt now includes stronger guidance to prevent this issue.

**Solution 2: Manual Fix (If Error Still Occurs)**

If your colleague encounters this error again:

1. **Identify the missing field** from the error message:
   ```
   Unable to resolve method: Applicant.loanType()
   ```
   → Missing field: `loanType` in `Applicant` type

2. **Download the DRL file** from the error logs or S3

3. **Add the missing field** to the `declare` statement:
   ```drl
   declare Applicant
       age: int
       annualIncome: double
       creditScore: int
       loanType: String  ← ADD THIS
   end
   ```

4. **Redeploy** using the fixed DRL file

**Solution 3: Validate DRL Before Deployment (Future Enhancement)**

Add DRL validation that checks:
- All fields used in rules exist in declare statements
- Parse rules to extract field references
- Compare against declared fields
- Reject DRL if fields are missing

**Prevention:**
- The prompt improvements should significantly reduce this issue
- If it persists, we can add automated DRL validation before deployment
- Consider using a stricter LLM model or adding retry logic with validation

---

## Issue 2: Docker Port Already Allocated

**Symptom:**
```
Bind for 0.0.0.0:8084 failed: port is already allocated
Container drools-chase-insurance-underwriting-rules is not running (status: created)
✗ FAILED: All deployments failed
```

**Root Cause:**
The port (e.g., 8084) is already in use by another Drools container. The orchestrator assigns ports sequentially starting from 8080.

**Solution 1: Remove Old Container**
```bash
# List all Drools containers
docker ps -a | grep drools

# Stop and remove the container using that port
docker rm -f drools-chase-loan-underwriting-rules

# Or remove all stopped Drools containers
docker ps -a | grep drools | grep -v 'drools-' | awk '{print $1}' | xargs docker rm -f
```

**Solution 2: Check Port Usage**
```bash
# See which containers are using which ports
docker ps --format "table {{.Names}}\t{{.Ports}}"

# Find which container is using port 8084
docker ps | grep 8084
```

**Solution 3: Clean Up All Dedicated Containers**
If you want to start fresh:
```bash
# Stop all dedicated Drools containers (keeps main drools container)
docker ps | grep 'drools-' | grep -v '^drools\s' | awk '{print $1}' | xargs docker stop
docker ps -a | grep 'drools-' | grep -v '^drools\s' | awk '{print $1}' | xargs docker rm
```

**Prevention:**
- Before deploying, check if the container already exists
- Use unique `bank_id` + `policy_type` combinations
- The system will try to reuse existing containers, but port conflicts can occur if containers are stopped but not removed

---

## Issue 2B: Container in "created" Status (Not Running)

**Symptom:**
```
ℹ Docker container already exists: chase-insurance-underwriting-rules
✗ Failed to deploy: Container drools-chase-insurance-underwriting-rules is not running (status: created)
```

**Root Cause:**
The Docker container was created in a previous deployment but never started successfully. It exists in "created" state instead of "running" state.

**Solution 1: Manual Cleanup (Immediate fix)**
```bash
# Remove the orphaned container
docker rm -f drools-chase-insurance-underwriting-rules

# Retry deployment
```

**Solution 2: Automatic Cleanup (✅ FIXED in latest code)**

The system now automatically detects and removes containers in "created" or "exited" status:

1. **Update your code** to get the latest fix in `ContainerOrchestrator.py`
2. **Restart backend**:
   ```bash
   docker-compose restart backend
   ```
3. **Retry deployment** - the system will auto-remove orphaned containers

**What the fix does:**
- Checks container status when detecting existing containers
- If status is not "running" or "healthy", automatically removes the container
- Creates a fresh container that starts properly

---

## Issue 3: Container Already Exists Error

**Symptom:**
```
Container indian-loan-underwriting-rules already exists
```

**Solution:**
The deployment automatically disposes and redeploys. If you see this, it's working as expected.

---

## Issue 4: OpenAI API Quota Exceeded

**Symptom:**
```
⚠ Error transforming rule with OpenAI: Error code: 429
{'error': {'message': 'You exceeded your current quota...', 'type': 'insufficient_quota'}}
```

**Impact:**
- **Low Impact**: Rules still get saved to database
- **Missing Feature**: Rules won't have user-friendly descriptions
- **Workaround**: The raw DRL rule text is still available

**Root Cause:**
The system uses OpenAI API to transform technical DRL rules into user-friendly descriptions. Your OpenAI API key has exceeded its quota.

**Solutions:**

1. **Add OpenAI Credits** (Recommended if you need user-friendly descriptions)
   - Go to https://platform.openai.com/account/billing
   - Add credits to your account
   - Retry the workflow

2. **Disable Rule Transformation** (Temporary workaround)
   - Edit environment variables to skip OpenAI transformation
   - Rules will still work, just without friendly descriptions

3. **Use Alternative LLM** (Future enhancement)
   - The system could be modified to use Watsonx or local LLM instead
   - Currently only supports OpenAI for rule transformation

**What Still Works:**
- ✅ Rule extraction from PDFs
- ✅ DRL rule generation
- ✅ Drools deployment
- ✅ Rule evaluation
- ✅ Database storage
- ❌ User-friendly rule descriptions (missing)

**Example Impact:**

Without transformation:
```json
{
  "rule_name": "L1: Age Requirement Check",
  "requirement": "when\n  $applicant : Applicant( age < 18 || age > 65 )\n  $decision : Decision()\nthen..."
}
```

With transformation (when quota available):
```json
{
  "rule_name": "L1: Age Requirement Check",
  "requirement": "Applicant must be between 18 and 65 years old to qualify for this policy"
}
```

---

## Issue 5: Database Migration Not Applied

**Symptom:**
- `level` column doesn't exist in `extracted_rules` table
- API returns errors about missing column

**Solution:**
Run the migration script in pgAdmin:
```sql
-- File: db/migrations/002_add_level_column_to_extracted_rules.sql
```

See [db/migrations/README.md](db/migrations/README.md) for detailed instructions.

---

## Debugging Tips

### 1. Check Generated DRL File

Look at the S3 URL in the response to download the generated DRL:
```json
{
  "drl_s3_url": "https://uw-data-extraction.s3.amazonaws.com/..."
}
```

### 2. Validate Declare Statements

Ensure all fields used in rules are declared:
```drl
declare Applicant
    age: int
    annualIncome: double
    creditScore: int
    loanType: String  ← Must be here if used in rules!
end

rule "Personal Loan Age Check"
    when
        $applicant : Applicant( loanType == "personal", age < 18 )  ← Uses loanType
        ...
```

### 3. Check Drools Logs

View container logs:
```bash
docker logs drools-indian-loan-underwriting-rules
```

### 4. Test with Simple DRL

If issues persist, test with a minimal DRL:
```drl
package com.underwriting.rules;

declare Applicant
    age: int
end

declare Decision
    approved: boolean
    reasons: java.util.List
end

rule "Initialize Decision"
    when
        not Decision()
    then
        Decision decision = new Decision();
        decision.setApproved(true);
        decision.setReasons(new java.util.ArrayList());
        insert(decision);
end

rule "Age Check"
    when
        $applicant : Applicant( age < 18 )
        $decision : Decision()
    then
        $decision.setApproved(false);
        $decision.getReasons().add("Applicant must be at least 18 years old");
        update($decision);
end
```

---

## Getting Help

If you continue to encounter issues:

1. **Collect Error Logs**: Save the complete error message
2. **Check DRL File**: Download from S3 and inspect declare statements
3. **Share Details**: Provide the error message, DRL file, and input data
4. **Try Hierarchical Mode**: Use `/process_policy_from_s3_hierarchical` endpoint which has improved prompts

For urgent issues, contact the development team with:
- Full error logs
- S3 URLs of generated files
- Policy document used
- Request/response payloads
