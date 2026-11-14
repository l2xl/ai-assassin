# API connection stop

The request is read by a worker thread, and the dispatch waits for its lines while it watches the
turn's stop. A stop (`interrupt`, or the turn's `stopped`) ends the dispatch at once as a connection
error, a wait for a loading model included, and shuts the request's socket down from the
dispatching thread: the worker's blocked read fails, and the server sees the client gone even when
it has not begun to answer — a llama.cpp server then cancels the task, freeing the GPU of a prompt
it was still reading. The connections a request opens are held for that, wrapping urllib's own, so
proxies from the environment still apply; one that connects after the stop closes before it sends.
Nothing of the stopped request reaches the session. A stop before the request was sent sends none.
