"""Startup-only method timing for JVDA debug sessions."""

from functools import wraps
import inspect
import itertools
import sys
import threading
import time
import traceback

from logHandler import log


# Take one snapshot when NVDA imports JVDA. When debug logging is off,
# timedClass returns each class unchanged: normal method calls pay no branch,
# clock, wrapper, or logging cost.
_ENABLED = log.isEnabledFor(log.DEBUG)
_callIds = itertools.count(1)
_threadState = threading.local()
_SLOW_CALL_SECONDS = 0.5
_SLOW_CALL_REPEAT_SECONDS = 1.0
_SLOW_STACK_METHODS = frozenset(("script_sayAll",))


def _watchSlowCall(callId, qualifiedName, threadId, finished):
	"""Log Python stacks while a known blocking entry point is still running."""
	waitSeconds = _SLOW_CALL_SECONDS
	while not finished.wait(waitSeconds):
		frame = sys._current_frames().get(threadId)
		if frame is None:
			return
		try:
			stack = "".join(traceback.format_stack(frame))
		finally:
			del frame
		log.debug(
			"JVDA TIMER slow id=%d %s still running; current stack:\n%s",
			callId, qualifiedName, stack,
		)
		waitSeconds = _SLOW_CALL_REPEAT_SECONDS


def _timedFunction(function, ownerName, methodName):
	qualifiedName = f"{ownerName}.{methodName}"
	isEntryPoint = methodName.startswith(("script_", "event_"))

	@wraps(function)
	def wrapper(*args, **kwargs):
		callId = next(_callIds)
		depth = getattr(_threadState, "depth", 0)
		_threadState.depth = depth + 1
		started = time.perf_counter_ns()
		finished = None
		if isEntryPoint:
			log.debug(
				"JVDA TIMER start id=%d depth=%d %s",
				callId, depth, qualifiedName,
			)
		if methodName in _SLOW_STACK_METHODS:
			finished = threading.Event()
			threading.Thread(
				target=_watchSlowCall,
				args=(callId, qualifiedName, threading.get_ident(), finished),
				name="jvdaSlowCallWatcher",
				daemon=True,
			).start()
		outcome = "returned"
		try:
			return function(*args, **kwargs)
		except BaseException:
			outcome = "raised"
			raise
		finally:
			if finished is not None:
				finished.set()
			elapsedMs = (time.perf_counter_ns() - started) / 1_000_000
			_threadState.depth = depth
			log.debug(
				"JVDA TIMER end id=%d depth=%d %s %.3f ms %s",
				callId, depth, qualifiedName, elapsedMs, outcome,
			)

	return wrapper


def timedClass(cls):
	"""Time every method defined directly by *cls* in startup debug mode."""
	if not _ENABLED:
		return cls
	ownerName = f"{cls.__module__}.{cls.__qualname__}"
	for name, attribute in tuple(vars(cls).items()):
		if isinstance(attribute, staticmethod):
			wrapped = staticmethod(
				_timedFunction(attribute.__func__, ownerName, name),
			)
		elif isinstance(attribute, classmethod):
			wrapped = classmethod(
				_timedFunction(attribute.__func__, ownerName, name),
			)
		elif isinstance(attribute, property):
			wrapped = property(
				_timedFunction(attribute.fget, ownerName, f"{name}.get")
					if attribute.fget else None,
				_timedFunction(attribute.fset, ownerName, f"{name}.set")
					if attribute.fset else None,
				_timedFunction(attribute.fdel, ownerName, f"{name}.delete")
					if attribute.fdel else None,
				doc=attribute.__doc__,
			)
		elif inspect.isfunction(attribute):
			wrapped = _timedFunction(attribute, ownerName, name)
		else:
			continue
		setattr(cls, name, wrapped)
	return cls
