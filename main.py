  File "/opt/render/project/src/.venv/lib/python3.14/site-packages/fastapi/routing.py", line 2734, in app
    await route.handle(scope, receive, send)
  File "/opt/render/project/src/.venv/lib/python3.14/site-packages/fastapi/routing.py", line 1281, in handle
    await super().handle(scope, receive, send)
  File "/opt/render/project/src/.venv/lib/python3.14/site-packages/starlette/routing.py", line 280, in handle
    await self.app(scope, receive, send)
  File "/opt/render/project/src/.venv/lib/python3.14/site-packages/fastapi/routing.py", line 158, in app
    await wrap_app_handling_exceptions(app, request)(scope, receive, send)
  File "/opt/render/project/src/.venv/lib/python3.14/site-packages/starlette/_exception_handler.py", line 53, in wrapped_app
    raise exc
  File "/opt/render/project/src/.venv/lib/python3.14/site-packages/starlette/_exception_handler.py", line 42, in wrapped_app
    await app(scope, receive, sender)
  File "/opt/render/project/src/.venv/lib/python3.14/site-packages/fastapi/routing.py", line 144, in app
    response = await f(request)
               ^^^^^^^^^^^^^^^^
  File "/opt/render/project/src/.venv/lib/python3.14/site-packages/fastapi/routing.py", line 706, in app
    raw_response = await run_endpoint_function(
                   ^^^^^^^^^^^^^^^^^^^^^^^^^^^^
    ...<3 lines>...
    )
    ^
  File "/opt/render/project/src/.venv/lib/python3.14/site-packages/fastapi/routing.py", line 354, in run_endpoint_function
    return await run_in_threadpool(dependant.call, **values)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/opt/render/project/src/.venv/lib/python3.14/site-packages/starlette/concurrency.py", line 34, in run_in_threadpool
    return await anyio.to_thread.run_sync(func)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/opt/render/project/src/.venv/lib/python3.14/site-packages/anyio/to_thread.py", line 65, in run_sync
    return await get_async_backend().run_sync_in_worker_thread(
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
        func, args, abandon_on_cancel=abandon_on_cancel, limiter=limiter
        ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
    )
    ^
  File "/opt/render/project/src/.venv/lib/python3.14/site-packages/anyio/_backends/_asyncio.py", line 2641, in run_sync_in_worker_thread
    return await future
           ^^^^^^^^^^^^
  File "/opt/render/project/src/.venv/lib/python3.14/site-packages/anyio/_backends/_asyncio.py", line 1033, in run
    result = context.run(func, *args)
  File "/opt/render/project/src/main.py", line 244, in get_pending_chemicals
    cursor.execute("""
    ~~~~~~~~~~~~~~^^^^
        SELECT id, name, brand, cas_number, capacity_value, capacity_unit, quantity, package_unit, unit,
        ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
    ...<4 lines>...
        ORDER BY id DESC;
        ^^^^^^^^^^^^^^^^^
    """)
    ^^^^
  File "/opt/render/project/src/.venv/lib/python3.14/site-packages/psycopg2/extras.py", line 236, in execute
    return super().execute(query, vars)
           ~~~~~~~~~~~~~~~^^^^^^^^^^^^^
psycopg2.errors.UndefinedColumn: column "remark" does not exist
LINE 3:                location, expiry_date, status, remark, create...
                                                      ^
INFO:     27.130.119.72:0 - "GET /notifications HTTP/1.1" 200 OK
INFO:     27.130.119.72:0 - "GET /requisitions HTTP/1.1" 500 Internal Server Error
ERROR:    Exception in ASGI application
Traceback (most recent call last):
  File "/opt/render/project/src/.venv/lib/python3.14/site-packages/uvicorn/protocols/http/h11_impl.py", line 416, in run_asgi
    result = await app(  # type: ignore[func-returns-value]
             ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
        self.scope, self.receive, self.send
        ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
    )
    ^
  File "/opt/render/project/src/.venv/lib/python3.14/site-packages/uvicorn/middleware/proxy_headers.py", line 63, in __call__
    return await self.app(scope, receive, send)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/opt/render/project/src/.venv/lib/python3.14/site-packages/fastapi/applications.py", line 1163, in __call__
    await super().__call__(scope, receive, send)
  File "/opt/render/project/src/.venv/lib/python3.14/site-packages/starlette/applications.py", line 96, in __call__
    await self.middleware_stack(scope, receive, send)
  File "/opt/render/project/src/.venv/lib/python3.14/site-packages/starlette/middleware/errors.py", line 186, in __call__
    raise exc
  File "/opt/render/project/src/.venv/lib/python3.14/site-packages/starlette/middleware/errors.py", line 164, in __call__
    await self.app(scope, receive, _send)
  File "/opt/render/project/src/.venv/lib/python3.14/site-packages/starlette/middleware/cors.py", line 96, in __call__
    await self.simple_response(scope, receive, send, request_headers=headers)
  File "/opt/render/project/src/.venv/lib/python3.14/site-packages/starlette/middleware/cors.py", line 154, in simple_response
    await self.app(scope, receive, send)
  File "/opt/render/project/src/.venv/lib/python3.14/site-packages/starlette/middleware/exceptions.py", line 63, in __call__
    await wrap_app_handling_exceptions(self.app, conn)(scope, receive, send)
  File "/opt/render/project/src/.venv/lib/python3.14/site-packages/starlette/_exception_handler.py", line 53, in wrapped_app
    raise exc
  File "/opt/render/project/src/.venv/lib/python3.14/site-packages/starlette/_exception_handler.py", line 42, in wrapped_app
    await app(scope, receive, sender)
  File "/opt/render/project/src/.venv/lib/python3.14/site-packages/fastapi/middleware/asyncexitstack.py", line 18, in __call__
    await self.app(scope, receive, send)
  File "/opt/render/project/src/.venv/lib/python3.14/site-packages/starlette/routing.py", line 670, in __call__
    await self.middleware_stack(scope, receive, send)
  File "/opt/render/project/src/.venv/lib/python3.14/site-packages/fastapi/routing.py", line 2734, in app
    await route.handle(scope, receive, send)
  File "/opt/render/project/src/.venv/lib/python3.14/site-packages/fastapi/routing.py", line 1281, in handle
    await super().handle(scope, receive, send)
  File "/opt/render/project/src/.venv/lib/python3.14/site-packages/starlette/routing.py", line 280, in handle
    await self.app(scope, receive, send)
  File "/opt/render/project/src/.venv/lib/python3.14/site-packages/fastapi/routing.py", line 158, in app
    await wrap_app_handling_exceptions(app, request)(scope, receive, send)
  File "/opt/render/project/src/.venv/lib/python3.14/site-packages/starlette/_exception_handler.py", line 53, in wrapped_app
    raise exc
  File "/opt/render/project/src/.venv/lib/python3.14/site-packages/starlette/_exception_handler.py", line 42, in wrapped_app
    await app(scope, receive, sender)
  File "/opt/render/project/src/.venv/lib/python3.14/site-packages/fastapi/routing.py", line 144, in app
    response = await f(request)
               ^^^^^^^^^^^^^^^^
  File "/opt/render/project/src/.venv/lib/python3.14/site-packages/fastapi/routing.py", line 706, in app
    raw_response = await run_endpoint_function(
                   ^^^^^^^^^^^^^^^^^^^^^^^^^^^^
    ...<3 lines>...
    )
    ^
  File "/opt/render/project/src/.venv/lib/python3.14/site-packages/fastapi/routing.py", line 354, in run_endpoint_function
    return await run_in_threadpool(dependant.call, **values)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/opt/render/project/src/.venv/lib/python3.14/site-packages/starlette/concurrency.py", line 34, in run_in_threadpool
    return await anyio.to_thread.run_sync(func)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/opt/render/project/src/.venv/lib/python3.14/site-packages/anyio/to_thread.py", line 65, in run_sync
    return await get_async_backend().run_sync_in_worker_thread(
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
        func, args, abandon_on_cancel=abandon_on_cancel, limiter=limiter
        ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
    )
    ^
  File "/opt/render/project/src/.venv/lib/python3.14/site-packages/anyio/_backends/_asyncio.py", line 2641, in run_sync_in_worker_thread
    return await future
           ^^^^^^^^^^^^
  File "/opt/render/project/src/.venv/lib/python3.14/site-packages/anyio/_backends/_asyncio.py", line 1033, in run
    result = context.run(func, *args)
  File "/opt/render/project/src/main.py", line 359, in get_requisitions
    cursor.execute("""
    ~~~~~~~~~~~~~~^^^^
        SELECT r.id, COALESCE(u.full_name, 'ไม่ระบุ') as requester_name, c.name as chemical_name, c.brand,
        ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
    ...<7 lines>...
        ORDER BY r.id DESC;
        ^^^^^^^^^^^^^^^^^^^
    """)
    ^^^^
  File "/opt/render/project/src/.venv/lib/python3.14/site-packages/psycopg2/extras.py", line 236, in execute
    return super().execute(query, vars)
           ~~~~~~~~~~~~~~~^^^^^^^^^^^^^
psycopg2.errors.UndefinedColumn: column r.remark does not exist
LINE 3: ..., c.package_unit as unit, r.status, r.approved_by, r.remark,
                                                              ^
INFO:     27.130.119.72:0 - "GET /chemicals HTTP/1.1" 200 OK
