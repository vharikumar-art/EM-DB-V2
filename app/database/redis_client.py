import redis.asyncio as redis

redis_client = None


async def connect_redis():
    global redis_client

    redis_client = redis.Redis(
        host="127.0.0.1",
        port=6379,
        db=0,
        decode_responses=True,
    )

    await redis_client.ping()
    print("Redis connected successfully")


async def close_redis():
    global redis_client

    if redis_client:
        await redis_client.aclose()
        redis_client = None
        print("Redis connection closed")