import asyncio
import re
from datetime import date, datetime
from decimal import Decimal

import httpx
from sqlalchemy import create_engine, text

from config import ADK_DB_CONN, FORECAST_API_URL

# -------------------------------------------------------------------
# Shared clients
# -------------------------------------------------------------------

# Created once and reused by all database tool calls.
db_engine = create_engine(
    ADK_DB_CONN,
    pool_pre_ping=True,
    pool_size=8,
    max_overflow=8,
)

# Created once and reused by all forecasting API tool calls.
http_client = httpx.AsyncClient(
    base_url=FORECAST_API_URL,
    timeout=httpx.Timeout(
        connect=10.0,
        read=30.0,
        write=30.0,
        pool=10.0,
    ),
)


# -------------------------------------------------------------------
# Database tools
# -------------------------------------------------------------------
def make_json_safe(value):
    """Convert database values into JSON-compatible values."""

    if isinstance(value, (date, datetime)):
        return value.isoformat()

    if isinstance(value, Decimal):
        return float(value)

    if isinstance(value, dict):
        return {
            key: make_json_safe(item)
            for key, item in value.items()
        }

    if isinstance(value, (list, tuple)):
        return [make_json_safe(item) for item in value]

    return value
def get_weather_schema() :
    """
    Return the columns and types of the predictions table.

    Call this before writing SQL.

    Field meanings:
    - forecast_origin: date from which the forecast was generated.
    - forecast_date: date the forecast is FOR.
    - forecast_step: days after forecast_origin.
    - predicted_temperature: temperature in degrees Celsius.
    - created_at: time the database row was created.

    Multiple rows can have the same city and forecast_date but different
    forecast_origin values. Prefer the newest forecast_origin.

    Returns:
        A dictionary containing column information or a safe error.
    """

    sql = """
        SELECT
            column_name,
            data_type,
            is_nullable
        FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name = 'predictions'
        ORDER BY ordinal_position
    """

    try:
        with db_engine.connect() as connection:
            result = connection.execute(text(sql))

            columns = [
                {
                    "name": row.column_name,
                    "type": row.data_type,
                    "nullable": row.is_nullable,
                }
                for row in result
            ]

        return {"columns": columns}

    except Exception as exc:
        print(f"[get_weather_schema ERROR] {exc}")

        return {
            "error": "The stored forecast structure is temporarily unavailable."
        }


def query_weather_db(sql: str):
    """
    Execute a read-only query against stored weather forecasts.

    The query may use SELECT, WITH, WHERE, ILIKE, BETWEEN, GROUP BY,
    ORDER BY, LIMIT, aggregates, subqueries, CASE and date functions.

    Always use forecast_date for the date the user is asking about.
    If multiple forecasts exist for the same forecast_date, prefer the
    row with the latest forecast_origin.

    Args:
        sql: A complete PostgreSQL SELECT query.

    Returns:
        Selected columns, resulting rows and row count.
    """

    cleaned_sql = sql.strip()
    lowered_sql = cleaned_sql.lower()

    if not lowered_sql.startswith(("select", "with")):
        return {
            "error": "Only read-only SELECT queries are permitted."
        }

    # Reject multiple SQL statements.
    sql_without_final_semicolon = cleaned_sql.rstrip(";")

    if ";" in sql_without_final_semicolon:
        return {
            "error": "Multiple SQL statements are not permitted."
        }

    forbidden_words = (
        "insert",
        "update",
        "delete",
        "drop",
        "alter",
        "truncate",
        "create",
        "grant",
        "revoke",
        "copy",
        "vacuum",
        "call",
    )

    for word in forbidden_words:
        if re.search(rf"\b{word}\b", lowered_sql):
            return {
                "error": "Only read-only SELECT queries are permitted."
            }

    print(f"[query_weather_db SQL] {cleaned_sql}")

    try:
        with db_engine.connect() as connection:
            result = connection.execute(text(cleaned_sql))

            columns = list(result.keys())
            rows = [
                make_json_safe(dict(row._mapping))
                for row in result.fetchall()
            ]

        return {
            "columns": columns,
            "rows": rows,
            "row_count": len(rows),
        }

    except Exception as exc:
        print(f"[query_weather_db ERROR] {exc}")

        return {
            "error": "The stored forecast query could not be completed."
        }


# -------------------------------------------------------------------
# Forecast API tools
# -------------------------------------------------------------------

async def predict_single(
    city: str,
    forecast_days: int,
):
    """
    Request a new forecast for one Saudi city.

    Use this only after query_weather_db returned zero rows for the
    requested future dates.

    Args:
        city: Supported Saudi city name.
        forecast_days: Number of future days from 1 through 30.

    Returns:
        The forecasting API response. Status may be completed, queued
        or failed.
    """

    city = city.strip()

    if not city:
        return {
            "status": "failed",
            "error": "A city is required.",
        }

    if not 1 <= forecast_days <= 30:
        return {
            "status": "failed",
            "error": "forecast_days must be between 1 and 30.",
        }

    try:
        response = await http_client.post(
            "/predict/single",
            json={
                "city": city,
                "forecast_days": forecast_days,
            },
        )

        try:
            data = response.json()
        except ValueError:
            data = {}

        if response.status_code >= 400:
            return {
                "status": "failed",
                "error": data.get(
                    "detail",
                    "The forecast request failed.",
                ),
            }

        return data

    except httpx.TimeoutException:
        return {
            "status": "failed",
            "error": "The forecasting service timed out.",
        }

    except httpx.RequestError as exc:
        print(f"[predict_single REQUEST ERROR] {exc}")

        return {
            "status": "failed",
            "error": "The forecasting service is unavailable.",
        }


async def predict_batch(
    requests: list[dict],
):
    """
    Request new forecasts for multiple Saudi cities.

    Use this only after checking stored forecasts first.

    Args:
        requests: A list containing city and forecast_days objects.
            Example:
            [
                {"city": "Riyadh", "forecast_days": 3},
                {"city": "Jeddah", "forecast_days": 3}
            ]

    Returns:
        The forecasting API response.
    """

    if not requests:
        return {
            "status": "failed",
            "error": "At least one forecast request is required.",
        }

    cleaned_requests = []

    for request in requests:
        city = str(request.get("city", "")).strip()

        try:
            forecast_days = int(request.get("forecast_days", 0))
        except (TypeError, ValueError):
            return {
                "status": "failed",
                "error": "forecast_days must be an integer.",
            }

        if not city:
            return {
                "status": "failed",
                "error": "Every request must include a city.",
            }

        if not 1 <= forecast_days <= 30:
            return {
                "status": "failed",
                "error": "forecast_days must be between 1 and 30.",
            }

        cleaned_requests.append(
            {
                "city": city,
                "forecast_days": forecast_days,
            }
        )

    try:
        response = await http_client.post(
            "/predict/batch",
            json=cleaned_requests,
        )

        try:
            data = response.json()
        except ValueError:
            data = {}

        if response.status_code >= 400:
            return {
                "status": "failed",
                "error": data.get(
                    "detail",
                    "The batch forecast request failed.",
                ),
            }

        return data

    except httpx.TimeoutException:
        return {
            "status": "failed",
            "error": "The forecasting service timed out.",
        }

    except httpx.RequestError as exc:
        print(f"[predict_batch REQUEST ERROR] {exc}")

        return {
            "status": "failed",
            "error": "The forecasting service is unavailable.",
        }


async def get_forecast_result(
    job_id: str,
):
    """
    Retrieve the result of a queued forecast job.

    Call this after predict_single or predict_batch returns status
    'queued'. If the returned status is pending or processing, call
    wait_for_forecast before trying again.

    Args:
        job_id: The job identifier returned by the prediction endpoint.

    Returns:
        The current job status and its result when completed.
    """

    job_id = job_id.strip()

    if not job_id:
        return {
            "status": "failed",
            "error": "A job identifier is required.",
        }

    try:
        response = await http_client.get(
            f"/predict/result/{job_id}"
        )

        try:
            data = response.json()
        except ValueError:
            data = {}

        if response.status_code == 404:
            return {
                "status": "failed",
                "error": "The forecast job was not found or expired.",
            }

        if response.status_code >= 400:
            return {
                "status": "failed",
                "error": data.get(
                    "detail",
                    "The forecast result could not be retrieved.",
                ),
            }

        return data

    except httpx.TimeoutException:
        return {
            "status": "failed",
            "error": "The forecasting service timed out.",
        }

    except httpx.RequestError as exc:
        print(f"[get_forecast_result REQUEST ERROR] {exc}")

        return {
            "status": "failed",
            "error": "The forecasting service is unavailable.",
        }


async def wait_for_forecast(
    seconds: int = 4,
):
    """
    Pause before checking a queued forecast again.

    Call this between forecast-result checks. Do not retry more than
    15 times.

    Args:
        seconds: Number of seconds to wait, from 1 through 10.

    Returns:
        Confirmation that the waiting period completed.
    """

    safe_seconds = max(1, min(int(seconds), 10))

    await asyncio.sleep(safe_seconds)

    return {
        "status": "waited",
        "seconds": safe_seconds,
    }


async def close_tool_connections():
    """
    Close shared HTTP and database resources during application shutdown.
    """

    await http_client.aclose()
    db_engine.dispose()