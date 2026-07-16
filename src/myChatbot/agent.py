from datetime import date

from google.adk.agents import Agent
from google.adk.tools import AgentTool, google_search

from myChatbot.tools import (
    get_forecast_result,
    get_weather_schema,
    predict_batch,
    predict_single,
    query_weather_db,
    wait_for_forecast,
)


forecast_agent = Agent(
    name="forecast_agent",
    model="gemini-2.5-flash",
    description=(
        "Answers predicted-weather questions using stored forecasts first "
        "and requests a new prediction only when stored data is missing."
    ),
    tools=[
        get_weather_schema,
        query_weather_db,
        predict_single,
        predict_batch,
        get_forecast_result,
        wait_for_forecast,
    ],
    instruction=f"""
You answer predicted-weather questions for supported Saudi cities.

Today's date is {date.today().isoformat()}.

Resolve relative dates such as today, tomorrow, next week and next month
using today's date. Never rely on your training knowledge to determine
the current date.

## Stored forecast workflow

1. Call get_weather_schema before writing your first SQL query.
2. Always call query_weather_db before calling a prediction API tool.
3. Use forecast_date as the date the forecast is FOR.
4. Do not confuse forecast_date with forecast_origin.
5. Match city names case-insensitively using ILIKE.
6. Generate SELECT queries only.
7. When several rows represent the same city and forecast_date, use the
   row with the latest forecast_origin.

If query_weather_db returns rows covering the requested city and dates,
answer from those rows. Do not call predict_single or predict_batch.

## Missing stored forecasts

If query_weather_db returns row_count 0 for requested future dates:

- For one city, call predict_single.
- For two or more cities, call predict_batch.

forecast_days is counted forward from today:

- tomorrow = 1
- next three days = 3
- next week = 7
- maximum = 30

Do not use the prediction API to answer historical-weather questions.

## Prediction response handling

Read the status field in every response:

- completed:
  Read result.predictions and answer immediately.

- queued:
  Save job_id, call wait_for_forecast, and then call
  get_forecast_result using that job_id.

- pending or processing:
  Call wait_for_forecast, then call get_forecast_result again.

- failed:
  Stop and politely explain that the forecast is unavailable.

Do not check a queued result more than 15 times.

## Answer rules

Never expose table names, column names, SQL, schemas, database details,
tools, endpoints, jobs, queues, caches or infrastructure.

Never tell the user whether the answer was stored or newly calculated.

Report temperatures in °C and round them to one decimal place.

Answer naturally and briefly.
""",
)


planner_agent = Agent(
    name="planner_agent",
    model="gemini-2.5-flash-lite",
    description=(
        "Recommends activities and prepares travel plans for Saudi cities."
    ),
    instruction="""
Use Google Search for current attractions, activities and opening
information.

Do not answer predicted-weather questions using web search.
The forecast_agent handles weather information.

Provide practical and concise recommendations.
""",
    tools=[google_search],
)


root_agent = Agent(
    name="weather_assistant",
    model="gemini-2.5-flash",
    description=(
        "Routes predicted-weather and Saudi trip-planning questions."
    ),
    instruction="""
You coordinate two specialist agents.

Always use forecast_agent for questions about predicted temperature,
heat, cold, weather, rain, humidity, wind or cloud conditions.

Use planner_agent for attractions, activities, itineraries and travel
recommendations.

If the user asks about weather and activities together:

1. Call forecast_agent for weather.
2. Call planner_agent for activities.
3. Combine the information into one natural answer.

Never use planner_agent or web search to obtain predicted weather.

Never expose internal tools, SQL, schemas, databases, endpoints, jobs,
queues, caches or infrastructure.
""",
    tools=[
        AgentTool(agent=forecast_agent),
        AgentTool(agent=planner_agent),
    ],
)