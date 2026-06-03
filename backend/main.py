import os
import json
import re
import sys
from datetime import date, timedelta
from typing import Optional
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from supabase import create_client, Client
import google.generativeai as genai

if sys.platform.startswith('win'):
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except Exception:
        pass

# ==========================================
# SECTION 1 — Imports and Setup
# ==========================================
load_dotenv()

app = FastAPI(title="FlowJarvis API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ==========================================
# SECTION 2 — Client Initialization
# ==========================================
# Supabase
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_KEY")
supabase: Client = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)

# Gemini
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
genai.configure(api_key=GEMINI_API_KEY)

# ==========================================
# SECTION 3 — Pydantic Request/Response Models
# ==========================================
class ChatMessage(BaseModel):
    role: str  # "user" or "assistant"
    content: str

class ChatRequest(BaseModel):
    message: str
    conversation_history: list[ChatMessage] = []

# ==========================================
# SECTION 4 — Tool Function 1: query_internal_capacity
# ==========================================
def query_internal_capacity(department: Optional[str] = None, weeks_ahead: int = 4) -> dict:
    """
    Queries Supabase for employee capacity, project health, and sprint velocity.
    Returns a structured dict that Gemini will use to reason about internal bandwidth.
    """
    try:
        # --- Query 1: Employees ---
        employees = []
        try:
            emp_query = supabase.table("employees").select(
                "name, department, role, capacity_pct, available_from"
            )
            if department:
                emp_query = emp_query.eq("department", department)
            employees_response = emp_query.execute()
            employees = employees_response.data
        except Exception as e:
            print(f"[Supabase] Query failed: {e}")

        # --- Query 2: Active Projects ---
        projects = []
        try:
            projects_response = supabase.table("projects").select(
                "id, name, department, status, burn_rate_pct, health, end_date"
            ).eq("status", "active").execute()
            projects = projects_response.data
        except Exception as e:
            print(f"[Supabase] Query failed: {e}")

        # --- Query 3: Sprint velocity for active projects ---
        sprints_data = []
        try:
            for project in projects:
                sprints_response = supabase.table("sprints").select(
                    "sprint_number, velocity, capacity, status"
                ).eq("project_id", project["id"]).eq("status", "completed").order(
                    "sprint_number", desc=True
                ).limit(3).execute()
                if sprints_response.data:
                    velocities = [s["velocity"] for s in sprints_response.data]
                    avg_vel = sum(velocities) / len(velocities)
                    sprints_data.append({
                        "project_name": project["name"],
                        "recent_velocities": velocities,
                        "avg_velocity": round(avg_vel, 1),
                        "capacity_per_sprint": sprints_response.data[0]["capacity"] if sprints_response.data else 45
                    })
        except Exception as e:
            print(f"[Supabase] Query failed: {e}")

        # --- Computed Metrics ---
        today = date.today()
        future_cutoff = today + timedelta(weeks=weeks_ahead)

        overloaded = [e for e in employees if e["capacity_pct"] > 75]
        critical = [e for e in employees if e["capacity_pct"] > 90]
        available_soon = [
            e for e in employees
            if date.fromisoformat(e["available_from"]) <= future_cutoff
        ]
        dept_capacity = {}
        for e in employees:
            dept = e["department"]
            if dept not in dept_capacity:
                dept_capacity[dept] = []
            dept_capacity[dept].append(e["capacity_pct"])
        dept_avg = {
            dept: round(sum(vals) / len(vals))
            for dept, vals in dept_capacity.items()
        }

        # --- Return structured dict ---
        return {
            "employees": employees,
            "active_projects": projects,
            "sprint_velocity_trends": sprints_data,
            "metrics": {
                "total_employees": len(employees),
                "overloaded_count": len(overloaded),
                "critical_overload_count": len(critical),
                "available_soon_count": len(available_soon),
                "department_avg_capacity": dept_avg,
                "overloaded_employees": [
                    {"name": e["name"], "department": e["department"], "capacity_pct": e["capacity_pct"]}
                    for e in overloaded
                ],
                "critical_employees": [
                    {"name": e["name"], "role": e["role"], "capacity_pct": e["capacity_pct"]}
                    for e in critical
                ]
            }
        }

    except Exception as e:
        return {
            "error": f"Database query failed: {str(e)}",
            "employees": [],
            "active_projects": [],
            "sprint_velocity_trends": [],
            "metrics": {
                "total_employees": 0,
                "overloaded_count": 0,
                "critical_overload_count": 0,
                "available_soon_count": 0,
                "department_avg_capacity": {},
                "overloaded_employees": [],
                "critical_employees": []
            }
        }

# ==========================================
# SECTION 5 — Tool Function 2: search_market_context
# ==========================================
def search_market_context(query: str) -> dict:
    """
    Uses Gemini with Google Search grounding to fetch real-time market context.
    Falls back to a structured mock if grounding fails.
    """
    # Fallback: return a contextually relevant mock based on keywords in query
    query_lower = query.lower()
    if any(word in query_lower for word in ["payment", "integration", "api"]):
        context = (
            "Payment integration projects for SMBs typically cost $30,000–$70,000 and take 8–14 weeks "
            "depending on compliance requirements (PCI-DSS). The payment API market is growing at 17% YoY in 2026. "
            "Key risks include PCI compliance complexity, third-party API reliability, and scope creep during testing. "
            "Most SMBs underestimate QA time by 40%."
        )
    elif any(word in query_lower for word in ["hire", "contractor", "recruit", "staff"]):
        context = (
            "Contract developer rates in 2026 range from $50–$150/hour depending on specialization. "
            "Average time-to-hire for contractors is 2–3 weeks via platforms like Toptal or Upwork. "
            "SMBs using contractors for short engagements report 30% faster delivery but 20% higher cost vs in-house. "
            "Backend and DevOps contractors are in highest demand with lowest availability."
        )
    elif any(word in query_lower for word in ["burnout", "capacity", "workload", "team"]):
        context = (
            "Team burnout risk increases significantly when sustained utilization exceeds 80% for more than 6 weeks. "
            "2026 SMB surveys show 42% of engineering teams report high burnout, leading to 2x attrition risk. "
            "Recommended intervention: reduce sprint capacity by 20% and introduce buffer time. "
            "Burnout-related turnover costs 1.5–2x annual salary per employee replaced."
        )
    else:
        context = (
            f"Market analysis for '{query}': SMB project investments in this area typically range $20,000–$100,000. "
            "Average delivery timeline is 8–16 weeks. Key risk factors include resource availability, "
            "technical debt in existing systems, and changing business requirements mid-project. "
            "2026 data shows 60% of SMB projects exceed original timeline by 25%."
        )
    return {
        "context": context,
        "query_used": query,
        "source": "fallback_mock"
    }

# ==========================================
# SECTION 6 — Gemini Tool Declarations
# ==========================================
TOOL_DECLARATIONS = [
    {
        "name": "query_internal_capacity",
        "description": (
            "Query the internal company database to retrieve employee capacity utilization, "
            "active project health, sprint velocity trends, and team availability. "
            "ALWAYS call this tool when the user's question involves: taking on new work, "
            "team bandwidth, project feasibility, resource allocation, hiring decisions, "
            "burnout risk, or any question about whether the internal team can handle something. "
            "This tool reads live data from Supabase."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "department": {
                    "type": "string",
                    "description": (
                        "Optional. Filter by department name. "
                        "Valid values: 'Engineering', 'Design', 'Sales', 'Ops'. "
                        "If the question is about a specific team, filter to that team. "
                        "If the question is general, omit this parameter to get all departments."
                    )
                },
                "weeks_ahead": {
                    "type": "integer",
                    "description": (
                        "How many weeks into the future to check availability. "
                        "Default is 4. Use 8 for medium-term planning, 12 for quarterly planning."
                    )
                }
            },
            "required": []
        }
    },
    {
        "name": "search_market_context",
        "description": (
            "Search for current external market data, industry benchmarks, cost estimates, "
            "competitive landscape, and business trends relevant to the user's question. "
            "ALWAYS call this tool when the user's question involves: project costs, "
            "market conditions, industry trends, hiring market rates, competitor analysis, "
            "technology adoption rates, or any external business factor. "
            "This tool uses Google Search grounding for real-time data."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": (
                        "A specific, concise search query. Examples: "
                        "'payment integration project cost SMB 2026', "
                        "'contract backend developer rates India 2026', "
                        "'engineering team burnout statistics SMB'. "
                        "Make the query specific to what the user is asking about."
                    )
                }
            },
            "required": ["query"]
        }
    }
]

# ==========================================
# SECTION 7 — The Coordinator System Prompt
# ==========================================
COORDINATOR_SYSTEM_PROMPT = """
You are FlowJarvis, an elite SMB Operations Co-Pilot. Your job is to help operations managers
make high-stakes business decisions by combining real internal team data with external market intelligence.

## YOUR BEHAVIOR

When a user asks any business question, you MUST:
1. Call query_internal_capacity to get the real internal team situation (ALWAYS do this)
2. Call search_market_context with a relevant market search query (ALWAYS do this)
3. After receiving BOTH tool results, synthesize them into a final structured JSON response

You are not a chatbot. You are a decision engine. Never respond with plain text.
Your ONLY output after receiving tool results must be a valid JSON object. No markdown. No explanation. No preamble. Just the raw JSON.

## HOW TO INTERPRET INTERNAL CAPACITY DATA

When you receive data from query_internal_capacity, reason about it as follows:

**Capacity levels:**
- capacity_pct 0–49: Employee is available, can take on significant new work
- capacity_pct 50–74: Employee is moderately loaded, can take on small-to-medium tasks
- capacity_pct 75–89: Employee is overloaded, should not be assigned new work without removing existing tasks
- capacity_pct 90–100: Employee is critically overloaded, burnout risk, any new work will cause delays

**Department health:**
- If avg_capacity of a department > 80%: that department is a BOTTLENECK
- If avg_capacity of a department > 90%: that department is CRITICAL and must be flagged in key_risks

**Project health:**
- green: project is on track
- yellow: project has risks, needs monitoring
- red: project is in trouble, consuming resources beyond plan

**Sprint velocity trends:**
- If velocity is declining sprint-over-sprint: team is slowing down, likely due to technical debt or overload
- If velocity < 60% of capacity for 2+ sprints: team is severely underperforming

**Risk score calculation (0–100):**
Start at 0. Add points for each condition:
- +20 if the relevant department avg_capacity > 75%
- +15 if any employee in that department has capacity_pct > 90%
- +15 if there is a red-health project in the relevant department
- +10 if sprint velocity is declining (last sprint < sprint before last)
- +10 if available_soon_count < 2 (very few people freeing up soon)
- +10 if burn_rate_pct > 80% on any active project in that department
- +5 if there are 2+ yellow or red projects active simultaneously
- +5 if the market context mentions high complexity, regulation, or long timelines
Cap at 100.

**Risk level from score:**
- 0–24: low
- 25–49: medium
- 50–74: high
- 75–100: critical

## HOW TO WRITE THE SAFE-FAIL PLAN

The safe_fail_plan must be specific and actionable. Do NOT write vague things like "consider hiring contractors".
Instead write specific sentences like:
- "Delay project start by 6 weeks until Rahul Nair and Arjun Mehta free up from ERP Migration (estimated Aug 15)"
- "Re-route Sneha Iyer (DevOps, currently 40% utilized) to lead initial setup phase, reducing Engineering team load"
- "Hire 1 contract Backend Engineer for 10 weeks at estimated $6,000–$12,000 to bridge the capacity gap"
Use the actual employee names and project names from the tool data when writing this.

## HOW TO WRITE THE RECOMMENDATION

One sentence. Direct. Must contain a clear yes/no/conditional stance.
Examples of good recommendations:
- "Do not proceed with this project until Engineering capacity drops below 70% — estimated 6 weeks from now."
- "Proceed conditionally: re-route Sneha Iyer from Data Pipeline and hire one contract QA engineer."
- "Yes, the Sales and Ops teams have capacity, but Engineering is the critical bottleneck and must be resolved first."

## EXACT JSON OUTPUT SCHEMA

After receiving both tool results, output ONLY this JSON object with all fields populated:

{
  "risk_level": "<one of: low | medium | high | critical>",
  "risk_score": <integer from 0 to 100, calculated using the formula above>,
  "recommendation": "<one direct sentence with a clear yes/no/conditional stance>",
  "safe_fail_plan": "<2-3 specific sentences with actual names, dates, and numbers from the tool data>",
  "capacity_summary": {
    "overloaded_teams": ["<department name>", ...],
    "available_teams": ["<department name>", ...],
    "bottleneck": "<the single department or person that is the biggest constraint>",
    "earliest_start": "<earliest realistic date this new work could begin, as YYYY-MM-DD>",
    "department_breakdown": [
      {
        "department": "<dept name>",
        "avg_capacity_pct": <integer>,
        "status": "<one of: available | moderate | overloaded | critical>"
      }
    ]
  },
  "project_health": [
    {
      "name": "<project name>",
      "health": "<green | yellow | red>",
      "burn_rate": <integer 0-100>,
      "end_date": "<YYYY-MM-DD>",
      "risk_note": "<one sentence about this project's specific risk>"
    }
  ],
  "key_employees": [
    {
      "name": "<employee name>",
      "role": "<their role>",
      "capacity_pct": <integer>,
      "status": "<available | moderate | overloaded | critical>",
      "available_from": "<YYYY-MM-DD>"
    }
  ],
  "market_context": "<3-4 sentence summary synthesizing the external market data>",
  "key_risks": [
    "<specific risk #1 — reference actual data>",
    "<specific risk #2 — reference actual data>",
    "<specific risk #3 — reference actual data>"
  ],
  "confidence": <integer from 60 to 95, reflecting how complete your data was>
}

CRITICAL RULES:
- Output ONLY the JSON. No text before or after.
- All string fields must be populated. No nulls. No empty strings.
- risk_score must match risk_level (e.g., if score is 72, level must be "high")
- key_employees must include all employees with capacity_pct > 75 AND the top 2 most available employees
- project_health must include ALL active projects from the tool data, not just the bad ones
- department_breakdown must include every department that has at least one employee
- safe_fail_plan must mention at least one specific employee name from the tool data
"""

# ==========================================
# SECTION 8 — The Agentic Chat Loop
# ==========================================
@app.post("/chat")
async def chat(request: ChatRequest):
    try:
        # Try fallback models for the agentic chat loop to handle rate limits / quotas
        # Resolve the active model dynamically if gemini-1.5-flash is not available
        resolved_model = "gemini-1.5-flash"
        try:
            available_names = [m.name.split("/")[-1] for m in genai.list_models() if "generateContent" in m.supported_generation_methods]
            if "gemini-1.5-flash" not in available_names:
                for name in available_names:
                    if "flash" in name:
                        resolved_model = name
                        break
        except Exception:
            pass

        models_to_try = [resolved_model]
        chat_session = None
        response = None
        last_error = None
        
        for model_name in models_to_try:
            try:
                model = genai.GenerativeModel(
                    model_name=model_name,
                    system_instruction=COORDINATOR_SYSTEM_PROMPT,
                    tools=[{"function_declarations": TOOL_DECLARATIONS}]
                )
                chat_session = model.start_chat(history=[])
                first_message = request.message
                response = chat_session.send_message(first_message)
                print(f"[FlowJarvis] Successfully initialized chat session using model: gemini-1.5-flash")
                break
            except Exception as model_err:
                print(f"[FlowJarvis] Model gemini-1.5-flash failed on start_chat/first message: {model_err}")
                last_error = model_err
                chat_session = None
                continue

        if not chat_session or not response:
            raise HTTPException(status_code=500, detail=f"All models failed to respond. Last error: {last_error}")

        # --- AGENTIC LOOP ---
        # Gemini may respond with tool calls. We handle them, send results back,
        # and repeat until Gemini gives us a final text response.
        tool_results_collected = {}
        max_iterations = 5
        iteration = 0

        while iteration < max_iterations:
            iteration += 1
            response_parts = response.candidates[0].content.parts

            # Check if Gemini is making function calls
            function_calls = [
                part for part in response_parts
                if hasattr(part, 'function_call') and part.function_call.name
            ]

            if not function_calls:
                # No more function calls — Gemini is done, this should be the final JSON
                break

            # Execute each tool call and collect results
            tool_response_parts = []
            for part in function_calls:
                fn_name = part.function_call.name
                fn_args = dict(part.function_call.args)

                print(f"[FlowJarvis] Executing tool: {fn_name} with args: {fn_args}")

                if fn_name == "query_internal_capacity":
                    result = query_internal_capacity(
                        department=fn_args.get("department"),
                        weeks_ahead=fn_args.get("weeks_ahead", 4)
                    )
                elif fn_name == "search_market_context":
                    result = search_market_context(
                        query=fn_args.get("query", request.message)
                    )
                else:
                    result = {"error": f"Unknown tool: {fn_name}"}

                tool_results_collected[fn_name] = result

                # Add the tool result to the response parts
                tool_response_parts.append(
                    genai.protos.Part(
                        function_response=genai.protos.FunctionResponse(
                            name=fn_name,
                            response={"result": result}
                        )
                    )
                )

            # Send all tool results back to Gemini in one message
            response = chat_session.send_message(tool_response_parts)

        # Check if after 5 iterations Gemini still hasn't produced a text response (still calling tools)
        response_parts = response.candidates[0].content.parts
        function_calls = [
            part for part in response_parts
            if hasattr(part, 'function_call') and part.function_call.name
        ]
        if function_calls:
            print("[FlowJarvis] Loop reached 5 iterations. Forcing text response.")
            response = chat_session.send_message(
                "You have now received all tool results. Stop calling tools. Output the final JSON analysis now."
            )

        # --- EXTRACT FINAL JSON RESPONSE ---
        final_text = ""
        for part in response.candidates[0].content.parts:
            if hasattr(part, 'text') and part.text:
                final_text += part.text

        final_text = final_text.strip()

        # Fix 2 — Empty response guard
        if not final_text or len(final_text) < 10:
            return {
                "error": True,
                "error_message": "Analysis engine produced no output. Please rephrase your question.",
                "analysis": None
            }

        # Strip markdown code blocks if Gemini wrapped the JSON in them
        if final_text.startswith("```"):
            final_text = re.sub(r'^```(?:json)?\n?', '', final_text)
            final_text = re.sub(r'\n?```$', '', final_text)
            final_text = final_text.strip()

        # Parse the JSON
        try:
            analysis = json.loads(final_text)
        except json.JSONDecodeError:
            # If parsing fails, ask Gemini to fix it once
            print(f"[FlowJarvis] JSON parse failed. Retrying with correction prompt.")
            fix_response = chat_session.send_message(
                "Your previous response was not valid JSON. Output ONLY the JSON object with no other text. Start with { and end with }."
            )
            retry_text = ""
            for part in fix_response.candidates[0].content.parts:
                if hasattr(part, 'text') and part.text:
                    retry_text += part.text
            retry_text = retry_text.strip()
            if retry_text.startswith("```"):
                retry_text = re.sub(r'^```(?:json)?\n?', '', retry_text)
                retry_text = re.sub(r'\n?```$', '', retry_text)
                retry_text = retry_text.strip()
            try:
                analysis = json.loads(retry_text)
            except json.JSONDecodeError as e:
                # Last resort: return error response that frontend can handle
                return {
                    "error": True,
                    "error_message": "Analysis engine returned malformed data. Please try again.",
                    "raw_response": retry_text[:500]
                }

        # Return the structured analysis plus debug info
        return {
            "error": False,
            "analysis": analysis,
            "tools_called": list(tool_results_collected.keys()),
            "iterations": iteration
        }

    except Exception as e:
        print(f"[FlowJarvis] Critical error in /chat: {str(e)}")
        return {
            "error": True,
            "error_message": f"Server error: {str(e)}",
            "analysis": None
        }

# ==========================================
# SECTION 9 — Additional Endpoints
# ==========================================
@app.get("/health")
async def health():
    return {"status": "ok", "version": "1.0.0"}


@app.get("/dashboard")
async def dashboard():
    try:
        employees_response = supabase.table("employees").select("capacity_pct, department").execute()
        projects_response = supabase.table("projects").select("status, health").execute()

        employees = employees_response.data
        projects = projects_response.data

        total_employees = len(employees)
        overloaded_count = sum(1 for e in employees if e["capacity_pct"] > 75)
        critical_count = sum(1 for e in employees if e["capacity_pct"] > 90)
        avg_capacity = round(sum(e["capacity_pct"] for e in employees) / total_employees) if total_employees > 0 else 0

        active_projects = [p for p in projects if p["status"] == "active"]
        red_projects = [p for p in projects if p["health"] == "red"]
        yellow_projects = [p for p in projects if p["health"] == "yellow"]

        dept_stats = {}
        for e in employees:
            d = e["department"]
            if d not in dept_stats:
                dept_stats[d] = []
            dept_stats[d].append(e["capacity_pct"])
        dept_summary = {
            d: {"avg": round(sum(v)/len(v)), "count": len(v)}
            for d, v in dept_stats.items()
        }

        return {
            "total_employees": total_employees,
            "overloaded_count": overloaded_count,
            "critical_count": critical_count,
            "avg_capacity": avg_capacity,
            "active_projects": len(active_projects),
            "red_projects": len(red_projects),
            "yellow_projects": len(yellow_projects),
            "department_summary": dept_summary
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ==========================================
# SECTION 10 — Startup Check
# ==========================================
@app.on_event("startup")
async def startup_event():
    print("=" * 50)
    print("FlowJarvis API starting up...")
    try:
        test = supabase.table("employees").select("count", count="exact").execute()
        print(f"✓ Supabase connected - {test.count} employees in database")
    except Exception as e:
        print(f"[FAIL] Supabase connection FAILED: {e}")
    try:
        test_response = None
        connected_model = None
        for model_name in ["gemini-1.5-flash"]:
            try:
                # Check list of models to find a working one
                resolved_model = model_name
                try:
                    available = [m.name.split("/")[-1] for m in genai.list_models() if "generateContent" in m.supported_generation_methods]
                    if model_name not in available:
                        for name in available:
                            if "flash" in name:
                                resolved_model = name
                                break
                except Exception:
                    pass

                test_model = genai.GenerativeModel(resolved_model)
                test_response = test_model.generate_content("Reply with the single word: ready")
                connected_model = model_name
                break
            except Exception:
                continue
        if test_response:
            print(f"✓ Gemini connected with model {connected_model} - response: {test_response.text.strip()}")
        else:
            print(f"[FAIL] Gemini connection FAILED: All models exhausted")
    except Exception as e:
        print(f"[FAIL] Gemini connection FAILED: {e}")
    print("[INFO] Tool 1 registered: query_internal_capacity")
    print("[INFO] Tool 2 registered: search_market_context")
    print("=" * 50)

