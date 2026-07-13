from google.adk.agents import Agent
from google.adk.tools import AgentTool, google_search
from config import DB_CONN
from sqlalchemy import create_engine, text


# -- Tool --

def query_weather_db(sql: str) -> dict:

    print(f"[query_weather_db SQL] {sql}")
    """Execute a read-only sql statements against the 'predictions' table only.
      return the resulting rows.
    
    Args:
    sql: A PostgreSQL SELECT statement against the predictions table.
    
    Returns:
        Returns forecasted weather 
    """

    if not sql.strip().lower().startswith("select"):
        return {"error": "Only SELECT queries are permitted."}
    
    engine = create_engine(DB_CONN)

    try:
        with engine.connect() as conn:
            result = conn.execute(text(sql))
            columns = list(result.keys())
            rows = [list(row) for row in result.fetchall()]

    except Exception as e:  
        print(f"[query_weather_db ERROR] {e}")
        return {"error": str(e)}
        
 # --- Sub-agent 1: forecasts from  DB ---
   
forecast_agent = Agent(
    name="forecast_agent",
    model="gemini-2.5-flash-lite",
    description="Answers questions about forecasted weather for Saudi cities from the predictions table",
    tools=[query_weather_db],
    instruction="""
     You answer questions about PREDICTED weather for Saudi cities using the 
    'predictions' table, via the query_weather_db tool.\n\n
    SQL rules:\n
    - Always match city case-insensitively: WHERE LOWER(city) = LOWER('Riyadh').\n
    - month, day, hour are integers (no quotes). Convert times to 24-hour 
    (3pm = 15).\n\n
    IMPORTANT — do NOT demand exact details. Infer the right query from how 
    specific the user is:\n
    - If they give a specific day and hour → filter to that exact row.\n
    - If they give only a month (e.g. 'weather in July', 'next month') → 
    aggregate across the whole month: SELECT AVG(predicted_temperature), 
    MIN(predicted_temperature), MAX(predicted_temperature), 
    AVG(relative_humidity_2m), SUM(precipitation), COUNT(*) 
    FROM predictions WHERE LOWER(city)=LOWER('Riyadh') AND month=7.\n
    - If they give a day but no hour → aggregate across that day (all 24 hours).\n
    - Only ask the user for more detail if the city itself is missing.\n\n
    Summarize results in plain language: typical temperature, range, humidity, 
    and whether it's rainy or clear. Report temperatures in Celsius.

"""

    )

 # --- Sub-agent 2: trip planner  ---

planner_agent = Agent(
    name="planner_agent",
    model="gemini-2.5-flash-lite",
    description="Recommends whether to visit a Saudi city and builds day-trip plans using web search.",
    instruction="""
         You help users decide whether to visit a Saudi city and build day-trip 
         itineraries. Use google_search for attractions, activities, and current info. 
         If weather matters to the recommendation, note that the forecast_agent handles 
         weather. Give practical, structured day plans.
""",
tools=[google_search]

)

# --- Root Agent ---

root_agent = Agent(
    name="weather_assistant",
    model="gemini-2.5-flash",
    description="Routes weather-forecast questions and trip-planning questions.",
    instruction="""
        You coordinate two specialist tools. Route based on what the user asks:\n\n
        ALWAYS use forecast_agent for ANYTHING about weather or temperature 
        predicted temperature, how hot/cold it is, humidity, rain, wind, or general
        'what is <city> like' / 'what's the weather in <city>' questions. These must 
        come from our prediction database, NOT web search.\n\n
        Use planner_agent ONLY for trip planning, activities, attractions, 
        recommendations on what to do or see, or whether a city is worth visiting.\n\n
        For a question that asks BOTH (e.g. 'what's the weather in Abha and what 
        should I do there'), FIRST call forecast_agent for the weather, THEN call 
        planner_agent for activities, and combine both into one answer.\n\n
        Never answer weather/temperature questions yourself or from planner_agent 
        they must always go through forecast_agent.
""",
tools=[
        AgentTool(agent=forecast_agent),
        AgentTool(agent=planner_agent),
    ]
)


