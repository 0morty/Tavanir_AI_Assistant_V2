import asyncio
from abc import ABC, abstractmethod
from collections.abc import AsyncGenerator, Awaitable, Callable
from contextlib import asynccontextmanager
from typing import TypeVar

from openai import (
    APIConnectionError,
    APIError,
    APIStatusError,
    APITimeoutError,
    AuthenticationError,
    RateLimitError,
)

from src.application.exceptions import ApplicationAPIError

T = TypeVar("T")


class BaseOpenAIService(ABC):
    """
    Abstract base class for OpenAI-based services to encapsulate common API
    error handling, metadata extraction, and exception translation.
    """

    @property
    @abstractmethod
    def _connection_error_cls(self) -> type[Exception]:
        """Returns the specific application ConnectionError class to raise."""
        pass

    @property
    @abstractmethod
    def _api_error_cls(self) -> type[ApplicationAPIError]:
        """Returns the specific application APIError class to raise."""
        pass

    @property
    def _auth_error_cls(self) -> type[Exception]:
        """Returns the specific application AuthError class. Defaults to _api_error_cls."""
        return self._api_error_cls

    @staticmethod
    def _extract_retry_after(err: APIError) -> float | None:
        """Attempts to parse the Retry-After header from the API response."""
        response = getattr(err, "response", None)
        if response is not None and hasattr(response, "headers"):
            retry_header = response.headers.get("retry-after")
            if retry_header:
                try:
                    return float(retry_header)
                except ValueError:
                    pass
        return None

    def _create_api_error(
        self,
        message: str,
        status_code: int | None = None,
        retry_after: float | None = None,
    ) -> ApplicationAPIError:
        """Instantiates the API error class with status code and retry metadata."""
        return self._api_error_cls(
            message, status_code=status_code, retry_after=retry_after
        )

    @asynccontextmanager
    async def _handle_api_call_scope(
        self, operation_name: str
    ) -> AsyncGenerator[None, None]:
        """Context manager to execute API operations and translate SDK errors to application exceptions."""
        try:
            yield
        except (APIConnectionError, APITimeoutError) as err:
            error_msg = f"Network/Timeout error during {operation_name}: {err}"
            raise self._connection_error_cls(error_msg) from err

        except AuthenticationError as err:
            error_msg = f"Authentication failed during {operation_name}: {err}"
            raise self._auth_error_cls(error_msg) from err

        except RateLimitError as err:
            error_msg = f"Rate limit exceeded during {operation_name}: {err}"
            status_code = getattr(err, "status_code", 429)
            retry_after = self._extract_retry_after(err)
            raise self._create_api_error(
                error_msg, status_code=status_code, retry_after=retry_after
            ) from err

        except APIStatusError as err:
            msg = getattr(err, "message", None) or str(err)
            error_msg = f"API error during {operation_name}: {msg}"
            status_code = getattr(err, "status_code", None)
            raise self._create_api_error(error_msg, status_code=status_code) from err

        except APIError as err:
            error_msg = f"OpenAI error during {operation_name}: {err}"
            raise self._api_error_cls(error_msg) from err

        except asyncio.CancelledError:
            raise

        except Exception as err:
            error_msg = f"Unexpected error during {operation_name}: {err}"
            raise self._api_error_cls(error_msg) from err

    async def _handle_api_call(
        self,
        async_request: Awaitable[T] | Callable[[], Awaitable[T]],
        operation_name: str,
    ) -> T:
        """Helper to execute an awaitable API call inside the error handling scope."""
        async with self._handle_api_call_scope(operation_name):
            if callable(async_request):
                return await async_request()
            return await async_request
