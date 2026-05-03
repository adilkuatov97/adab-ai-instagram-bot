# TODO — Future Improvements

## DebounceService

- [ ] Replace JSON-array-in-string buffer with Redis RPUSH for atomic appends
      (eliminates race condition on simultaneous webhooks)

- [ ] Save reference to asyncio.create_task to prevent GC collection during
      3-sec wait (low priority, current task lifetime makes this unlikely)
