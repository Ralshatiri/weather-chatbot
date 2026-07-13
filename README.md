# Weather Temperature Prediction ML Project

## Table of Contents

* [Project Overview](#project-overview)
* [Project Objective](#project-objective)
* [Repository Structure](#repository-structure)
* [Deployment Architecture](#deployment-architecture)
* [Main Deployment Components](#main-deployment-components)
* [How the Pipeline System Works](#how-the-pipeline-system-works)
* [How the Prediction System Works](#how-the-prediction-system-works)
* [How to Run Locally](#how-to-run-locally)
* [How to Run in the Cloud](#how-to-run-in-the-cloud)
* [Worker Auto Scaling](#worker-auto-scaling)
* [API Testing](#api-testing)
* [Troubleshooting Notes](#troubleshooting-notes)

---

## Project Overview

This project builds a complete machine learning workflow to predict temperature using weather observations from multiple cities in Saudi Arabia.

The workflow includes data ingestion, database storage, preprocessing, model training, model evaluation, API prediction, asynchronous job processing, caching, and cloud deployment. The project is containerized using Docker to make the environment reproducible locally and in the cloud.

---

## Project Objective

The main goal is to predict temperature using weather-related features such as city, humidity, precipitation, pressure, cloud cover, wind speed, wind gusts, and time-based variables.

This project demonstrates a full ML workflow, including:

* Loading raw weather data
* Storing raw and processed data in PostgreSQL
* Cleaning and preprocessing the data
* Training an XGBoost regression model for temperature prediction
* Saving the trained model artifact
* Serving predictions through a FastAPI application
* Using Redis for caching and job status storage
* Using RabbitMQ for background prediction jobs
* Running prediction workers separately from the API
* Deploying the system locally using Docker Compose
* Deploying the system on AWS using Fargate, EC2, Load Balancer, Auto Scaling Groups, S3, Parameter Store, CloudWatch, Redis, RabbitMQ, and PostgreSQL

---

## Repository Structure

```text

sql/
└── database schema and table creation scripts

src/
├── api/
│   └── FastAPI prediction endpoints
│
├── worker/
│   └── background prediction worker
│
├── Preprocess/
│   └── data cleaning and preprocessing scripts
│
├── model_training/
│   └── model training and evaluation code
│
├── config.py
    └── environment variable and database configuration

```

---

## Deployment Architecture

The final deployment has two main parts:

1. **ML pipeline deployment**: runs as an AWS Fargate task to load data, preprocess it, train the model, save data in PostgreSQL, and upload the trained model to S3.
2. **prediction deployment**: runs as a FastAPI service and background worker system. The API receives prediction requests, sends jobs to RabbitMQ, and workers process those jobs asynchronously.

Instead of making the API perform the prediction directly, the API creates a prediction job and sends it to RabbitMQ. A separate worker service consumes the job, downloads or loads the trained model from S3, performs the prediction, stores the result, and saves the prediction history.

```text
 ML Pipeline:

AWS Fargate Task
    ↓
Load raw weather data
    ↓
Preprocess and train model
    ↓
Stores in PostgreSQL database + saves model to S3 


 Prediction System:

Client
    ↓
Application Load Balancer
    ↓
API Auto Scaling Group
    ↓
Redis Cache / Job Status
    ↓
RabbitMQ Queue
    ↓
Worker Auto Scaling Group
    ↓
Redis Result Storage + PostgreSQL Prediction History
```

Additional services used:

```text
AWS Fargate:
- runs the ML pipeline as a containerized task
- stops after the pipeline finishes


Redis:
- prediction cache
- job status storage
- prediction result storage

S3:
- stores the trained model artifact
- stores the weather raw csv data

AWS Systems Manager Parameter Store:
- stores cloud configuration and secrets

CloudWatch:
- stores RabbitMQ queue depth metric
- triggers worker scale-out and scale-in alarms
```

---

## Main Deployment Components

### 1. AWS Fargate Pipeline Task

AWS Fargate is used to run the ML pipeline in the cloud.

The pipeline is not a service that needs to stay running all the time. It is a job that runs when we need to load data, preprocess data, train the model, and update the model artifact. Because of that, Fargate is a good choice because it can run the containerized pipeline task and stop after the task finishes.

The Fargate pipeline is responsible for:

* Pulling the Docker image
* Loading raw weather data
* Storing raw data in PostgreSQL
* Preprocessing the weather data
* Training the temperature prediction model
* Saving the trained model artifact
* Uploading the model artifact to S3


---

### 2. FastAPI Application

The FastAPI application receives prediction requests.

In the cloud, it runs inside the API EC2 instances managed by the API Auto Scaling Group.


The API is responsible for:

* Receiving prediction requests
* Checking Redis for cached results
* Creating a `job_id`
* Saving pending job status in Redis
* Publishing the job to RabbitMQ
* Returning the `job_id` to the user

---

### 3. RabbitMQ

RabbitMQ is used as the message queue between the API and the worker. RabbitMQ allows the system to handle prediction requests asynchronously. This means the API does not need to wait for the model prediction to finish before responding to the user.

---

### 4. Prediction Worker

The worker runs separately from the API.

The worker is responsible for:

* Connecting to RabbitMQ
* Consuming prediction jobs
* Connecting to Redis
* Downloading the trained model from S3 if needed
* Loading the model
* Running predictions
* Saving prediction results in Redis
* Saving prediction history in PostgreSQL
* Acknowledging completed RabbitMQ messages

---

### 5. Redis

Redis is used for two main purposes:

```text
1. Prediction caching
2. Job status and result storage
```

When the API receives a prediction request, it first checks Redis. If the same input was already predicted before, the cached result can be returned faster without sending a new job to RabbitMQ.

Redis also stores the status of each prediction job:

```text
pending
completed
failed
```

---

### 6. PostgreSQL

PostgreSQL stores the project data and prediction history.

It is used for:

* Raw weather data
* Processed weather data
* Saved prediction records

The Fargate pipeline writes raw and processed data to PostgreSQL. The worker saves completed predictions into PostgreSQL so that prediction history can be reviewed later.

---

### 7. S3

S3 stores the trained model artifact. The worker downloads the model from S3 when it starts.

---

### 8. Parameter Store

AWS Systems Manager Parameter Store is used to store cloud configuration values and secrets.

The cloud deployment does not depend on a local `.env` file. Instead, the EC2 launch templates read values from Parameter Store and pass them to the Docker containers as environment variables.

---

## How the Pipeline System Works

The pipeline flow is:

```text
1. The AWS Fargate task starts the pipeline container.
2. The pipeline reads the required configuration.
3. The pipeline loads the raw weather dataset.
4. The raw data is stored in PostgreSQL.
5. The preprocessing step cleans and transforms the data.
6. The processed data is stored or prepared for training.
7. The model training step trains the temperature prediction model.
8. The trained model artifact is saved.
9. The model artifact is uploaded to S3.
10. The Fargate task finishes and stops.
```

This design keeps the training pipeline separate from the live prediction system. The API and worker do not retrain the model. They use the model artifact that was already created by the pipeline and stored in S3.

---

## How the Prediction System Works

The prediction flow is:

```text
1. User sends a prediction request to the API.
2. The request reaches the Application Load Balancer.
3. The Load Balancer forwards the request to an API instance.
4. The API checks Redis for a cached prediction.
5. If a cached result exists, the API returns it.
6. If no cached result exists, the API creates a new job_id.
7. The API stores the job status as pending in Redis.
8. The API publishes the prediction job to RabbitMQ.
9. The API returns the job_id to the user.
10. A worker consumes the job from RabbitMQ.
11. The worker loads the trained model.
12. The worker runs the prediction.
13. The worker stores the result in Redis.
14. The worker saves the prediction history in PostgreSQL.
15. The user checks the result using the job_id.
```

This design is better than direct prediction because it separates request handling from heavy model processing.

---

## How to Run Locally

The local setup uses Docker Compose. The local environment runs the database, Redis, RabbitMQ, API, worker, and pipeline containers.

### 1. Create a `.env` File

Create a `.env` file in the project root.

Example:

```env
DB_HOST=
DB_PORT=
POSTGRES_DB=
POSTGRES_USER=
POSTGRES_PASSWORD=

REDIS_HOST=
REDIS_PORT=
REDIS_DB=
REDIS_TTL_SECONDS=
JOB_TTL_SECONDS=

RABBITMQ_HOST=
RABBITMQ_PORT=
RABBITMQ_USER=
RABBITMQ_PASSWORD=
RABBITMQ_QUEUE=

MODEL_S3_BUCKET=
RAW_DATA_S3_KEY=
MODEL_S3_KEY=

```

---

### 2. Build the Docker Image

```bash
docker compose build
```

---

### 3. Start the Infrastructure Services

```bash
docker compose up -d database redis rabbitmq
```

Check that the containers are running:

```bash
docker compose ps
```

---

### 4. Run the ML Pipeline

```bash
docker compose up pipeline
```

The pipeline should:

```text
1. Load raw weather data
2. Store raw data in PostgreSQL
3. Preprocess the data
4. Train the model
5. Save the model artifact
6. Upload the model artifact to S3
```

---

### 5. Start the API and Worker

```bash
docker compose up -d --no-deps prediction worker
```

The API will be available at:

```text
http://localhost:8000
```

API documentation:

```text
http://localhost:8000/docs
```

RabbitMQ dashboard:

```text
http://localhost:15672
```


---

### 6. Test the Local API

Health check:

```bash
curl http://localhost:8000/health
```

Expected response:

```json
{
  "status": "running"
}
```

Single prediction request:

```bash
curl -s -X POST "http://localhost:8000/predict/single" \
-H "Content-Type: application/json" \
-d '{
  "city": "Riyadh",
  "relative_humidity_2m": 20,
  "precipitation": 0,
  "weather_code": 0,
  "surface_pressure": 1008,
  "cloud_cover": 10,
  "wind_speed_10m": 12,
  "wind_direction_10m": 90,
  "wind_gusts_10m": 18,
  "month": 7,
  "day": 4,
  "hour": 15,
  "temperature_lag_24": 39,
  "temperature_rolling_mean_24": 38,
  "temperature_rolling_std_24": 2,
  "temperature_lag_720": 36
}'
```

Expected response:

```json
{
  "status": "queued",
  "job_id": "...",
  "message": "Single prediction job queued. Check result using /predict/result/{job_id}"
}
```

Then use the returned `job_id`:

```bash
curl http://localhost:8000/predict/result/JOB_ID
```

Expected completed response:

```json
{
  "status": "completed",
  "job_type": "single_prediction",
  "result": {
    "predicted_temperature": 38.2,
    "source": "worker"
  }
}
```

---

## How to Run in the Cloud


The cloud deployment is already prepared using:

```text
AWS Fargate for the ML pipeline
EC2 for PostgreSQL
EC2 for Redis and RabbitMQ
Application Load Balancer for the API
API Auto Scaling Group
Worker Auto Scaling Group
S3 for the trained model
Parameter Store for environment variables and secrets
CloudWatch for queue-depth monitoring and worker autoscaling
```


---

### 1. Start the Required Cloud Resources

Before testing the cloud API, make sure the main cloud resources are running.

Required resources:

```text
1. Database EC2
2. Queue EC2
3. API Auto Scaling Group instance
4. Worker Auto Scaling Group instance
```

The Database EC2 runs PostgreSQL.

The Queue EC2 runs:

```text
Redis
RabbitMQ
```

The API instance runs the FastAPI container.

The Worker instance runs the prediction worker container.

---

### 2. Start the Database EC2 and PostgreSQL Container

If the Database EC2 instance is stopped, start it from the AWS EC2 console.

After the instance is running, connect to it using SSH.

Then check the containers:

```bash
sudo docker compose ps -a
```

or:

```bash
sudo docker ps -a
```

Find the PostgreSQL container name.

Then start the PostgreSQL container:

```bash
sudo docker start POSTGRES_CONTAINER_NAME
```

Example:

```bash
sudo docker start weather-database
```

Check that it is running:

```bash
sudo docker ps
```


---

### 3. Start the Queue EC2 and Queue Containers

If the Queue EC2 instance is stopped, start it from the AWS EC2 console.

After the instance is running, connect to it using SSH.

Check the containers:

```bash
sudo docker ps -a
```

Start Redis:

```bash
sudo docker start REDIS_CONTAINER_NAME
```

Start RabbitMQ:

```bash
sudo docker start RABBITMQ_CONTAINER_NAME
```

Example:

```bash
sudo docker start weather-redis
sudo docker start weather-rabbitmq
```

Check that both containers are running:

```bash
sudo docker ps
```
---

### 4. Check the API Auto Scaling Group

The API should run from the API Auto Scaling Group.


The API ASG should launch an EC2 instance automatically.

After the API instance is running, the launch template should automatically start the API container.

To check manually, connect to the API EC2 instance and run:

```bash
sudo docker ps
```

Expected API container:

```text
weather-api
```

If the container exists but is stopped:

```bash
sudo docker start weather-api
```
``

The API container should run this command:

```bash
uvicorn src.api.prediction:app --host 0.0.0.0 --port 8000
```

---

### 5. Check the Worker Auto Scaling Group

The worker should run from the Worker Auto Scaling Group.

In the AWS console, open the Worker Auto Scaling Group and make sure:


The Worker ASG should launch an EC2 instance automatically.

After the worker instance is running, connect to it and check the container:

```bash
sudo docker ps
```

Expected worker container:

```text
weather-worker
```

If the container exists but is stopped:

```bash
sudo docker start weather-worker
```

Check the worker logs:

```bash
sudo docker logs --tail=100 weather-worker
```

Expected worker behavior:

```text
1. Connects to Redis
2. Connects to RabbitMQ
3. Downloads the trained model from S3
4. Loads the model
5. Waits for prediction jobs from RabbitMQ
```

Expected worker command:

```bash
python -u -m src.worker.prediction_worker
```

---

### 6. Run the ML Pipeline on AWS Fargate

The ML pipeline is deployed as an AWS Fargate task.

This task is used when we want to:

```text
1. Load or refresh the weather data
2. Preprocess the data
3. Train or update the model
4. Store data in PostgreSQL
5. Upload the trained model artifact to S3
```

The pipeline does not need to run all the time. It runs only when needed, then stops.

To run the pipeline:

```text
1. Open the AWS ECS console.
2. Open the cluster used for the weather project.
3. Choose the pipeline task definition.
4. Select Run task.
5. Choose Fargate as the launch type.
6. Select the correct VPC and subnets.
7. Select the security group that can connect to the PostgreSQL EC2 instance.
8. Run the task.
```

After starting the task, check the task logs in CloudWatch.

The pipeline should complete these steps:

```text
1. Read the raw weather data
2. Store raw data in PostgreSQL
3. Build processed weather data
4. Train the XGBoost regression model
5. Save the model artifact
6. Upload the model artifact to S3
```

The trained model should be stored in S3.

Example:

```text
Bucket: amzn-s3-bucker-weather
Key: models/xgboost_model.joblib
```

The worker later downloads this model from S3 during startup.

---

### 7. Check the Load Balancer

After the API instance is running, test the Load Balancer health endpoint.

```bash
curl http://LOAD_BALANCER_DNS/health
```

Expected response:

```json
{
  "status": "running"
}
```

You can also open the API documentation in the browser:

```text
http://LOAD_BALANCER_DNS/docs
```

---

### 8. Test a Cloud Prediction Request

Send a single prediction request through the Load Balancer:

```bash
curl -s -X POST "http://LOAD_BALANCER_DNS/predict/single" \
-H "Content-Type: application/json" \
-d '{
  "city": "Riyadh",
  "relative_humidity_2m": 20,
  "precipitation": 0,
  "weather_code": 0,
  "surface_pressure": 1008,
  "cloud_cover": 10,
  "wind_speed_10m": 12,
  "wind_direction_10m": 90,
  "wind_gusts_10m": 18,
  "month": 7,
  "day": 4,
  "hour": 15,
  "temperature_lag_24": 39,
  "temperature_rolling_mean_24": 38,
  "temperature_rolling_std_24": 2,
  "temperature_lag_720": 36
}'
```

Expected response:

```json
{
  "status": "queued",
  "job_id": "...",
  "message": "Single prediction job queued. Check result using /predict/result/{job_id}"
}
```

This means the API successfully created a prediction job and sent it to RabbitMQ.

---

### 9. Check the Prediction Result

Use the returned `job_id` to check the prediction result:

```bash
curl http://LOAD_BALANCER_DNS/predict/result/JOB_ID
```

If the worker has not finished yet, the result may still be pending:

```json
{
  "status": "pending"
}
```

After the worker finishes, the expected response is:

```json
{
  "status": "completed",
  "job_type": "single_prediction",
  "result": {
    "predicted_temperature": 38.2,
    "source": "worker"
  }
}
```

---

### 10. Check RabbitMQ Queue

On the Queue EC2 instance, check RabbitMQ queue status:

```bash
curl -s -u username:password http://localhost:15672/api/queues/%2F/weather_prediction_jobs | jq '{messages: .messages, ready: .messages_ready, unacked: .messages_unacknowledged, consumers: .consumers}'
```

Meaning:

```text
messages = total messages in the queue
ready = jobs waiting to be consumed
unacked = jobs taken by a worker but not acknowledged yet
consumers = active workers connected to RabbitMQ
```

If the system is working, the queue should receive jobs when prediction requests are sent, and the worker should consume them.

---

### 11. Check PostgreSQL Prediction History

On the Database EC2 instance, connect to the PostgreSQL container:

```bash
sudo docker exec -it POSTGRES_CONTAINER_NAME psql -U postgres_user -d postgres_db
```

Then run:

```sql
SELECT COUNT(*) FROM predictions;
SELECT * FROM predictions ORDER BY id DESC LIMIT 5;
```

This confirms that completed predictions are being saved in PostgreSQL.

---

### 12. Check the Model in S3

The worker depends on the trained model artifact stored in S3.

Check that the model exists:

```text
s3://amzn-s3-bucker-weather/models/xgboost_model.joblib
```

If the model is missing, run the Fargate pipeline task again or upload the model artifact to S3.



## Worker Auto Scaling

The worker workload is not based on HTTP traffic. It is based on the number of prediction jobs waiting in RabbitMQ.

Because of that, the worker should not scale based only on CPU. Instead, the worker scales based on RabbitMQ queue depth.

Queue depth means:

```text
How many prediction jobs are waiting in RabbitMQ.
```

The Queue EC2 publishes a custom CloudWatch metric for example:

```text
Namespace: WeatherML/RabbitMQ
Metric name: QueueDepth
Dimension: QueueName = weather_prediction_jobs
```

Scale-out behavior:

```text
If QueueDepth becomes high, CloudWatch triggers the worker scale-out alarm.
The Worker Auto Scaling Group adds another worker instance.
```

Scale-in behavior:

```text
If QueueDepth stays empty for a period of time, CloudWatch triggers the worker scale-in alarm.
The Worker Auto Scaling Group removes the extra worker instance.
```

The Worker ASG minimum capacity stays at `1`, so the final worker is not removed during normal operation.

If the system is intentionally stopped to reduce cost, the Worker ASG desired capacity can be set to `0` manually.
