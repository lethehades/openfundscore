from __future__ import annotations

import json
import unittest
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta, tzinfo
from types import MappingProxyType
from unittest.mock import patch
from zoneinfo import ZoneInfoNotFoundError

from openfundscore.official_providers import (
    FixedHostHttpClient,
    HttpRequest,
    HttpResponse,
    LocalRateLimiter,
    ProviderHttpError,
    SecEdgarSubmissionsAdapter,
    WorldBankIndicatorsAdapter,
)
from openfundscore.provider_sdk import (
    AuthenticationMode,
    IngestionDenied,
    ProviderCapability,
    RightsMode,
    SourceType,
)
from openfundscore.validation import validate_record


class OfficialProviderContractTests(unittest.TestCase):
    def test_macro_observation_is_a_valid_authorized_data_plane(self) -> None:
        self.assertEqual(
            ProviderCapability.GET_MACRO_SERIES.value,
            "get_macro_series",
        )
        record = {
            "provider_id": "world-bank-indicators-v2",
            "provider_record_id": "wb:1:US:NY.GDP.MKTP.CD:2024",
            "namespace": "canonical_observation",
            "source_type": "index_or_macro_official_source",
            "jurisdiction": "US",
            "entity_type": "macro_observation",
            "entity_id": "wb:1:US:NY.GDP.MKTP.CD",
            "field": "value",
            "value": 100.0,
            "unit": "current US$",
            "currency": "USD",
            "timezone": "UTC",
            "period": "2024",
            "frequency": "annual",
            "publication_lag": None,
            "revision": "latest API view; observations may be revised",
            "vintage": "2026-08-20",
            "as_of": "2024-01-01T00:00:00Z",
            "published_at": "2026-08-21T00:00:00Z",
            "fetched_at": "2026-08-21T00:00:00Z",
            "valid_from": "2024-01-01T00:00:00Z",
            "valid_to": "2025-01-01T00:00:00Z",
            "source_url": (
                "https://api.worldbank.org/v2/country/US/indicator/"
                "NY.GDP.MKTP.CD?format=json&page=1&per_page=1&source=1"
            ),
            "source_document_hash": "sha256:synthetic",
            "methodology": "Current World Bank API view without historical vintages.",
            "point_in_time_status": "not_point_in_time",
            "quality_state": "unverified",
            "rights": {
                "mode": "derived_only",
                "terms_url": (
                    "https://www.worldbank.org/en/about/legal/terms-of-use-for-datasets"
                ),
                "cache_allowed": True,
                "derived_works_allowed": True,
                "redistribution_allowed": False,
                "attribution_required": True,
                "public_display_allowed": False,
                "retention_days": 30,
                "reviewed_at": "2026-08-21T00:00:00Z",
            },
        }
        self.assertIsNone(
            validate_record(
                "provider_record",
                record,
                schema_version="0.2.0",
                evaluation_timestamp="2026-08-21T00:00:00Z",
            )
        )


class RecordingTransport:
    def __init__(self, response: HttpResponse) -> None:
        self.response = response
        self.requests: list[HttpRequest] = []

    def __call__(self, request: HttpRequest) -> HttpResponse:
        self.requests.append(request)
        return self.response


class QueueTransport:
    def __init__(self, responses: list[HttpResponse]) -> None:
        self.responses = responses
        self.requests: list[HttpRequest] = []

    def __call__(self, request: HttpRequest) -> HttpResponse:
        self.requests.append(request)
        return self.responses.pop(0)


class FixedHostHttpClientTests(unittest.TestCase):
    def test_injected_transport_receives_only_fixed_https_host_and_encoded_query(
        self,
    ) -> None:
        transport = RecordingTransport(
            HttpResponse(
                status=200,
                headers={"Content-Type": "application/json; charset=utf-8"},
                body=b'{"ok":true}',
            )
        )
        client = FixedHostHttpClient(
            host="data.sec.gov",
            transport=transport,
            connect_timeout=2.0,
            read_timeout=3.0,
            max_response_bytes=1024,
        )

        response = client.get_json(
            path="/submissions/CIK0000320193.json",
            query={"a": "space value"},
            headers={"User-Agent": "OpenFundScore security@openfundscore.org"},
        )

        self.assertEqual(response.document, {"ok": True})
        self.assertEqual(len(transport.requests), 1)
        request = transport.requests[0]
        self.assertEqual(request.scheme, "https")
        self.assertEqual(request.host, "data.sec.gov")
        self.assertEqual(
            request.target,
            "/submissions/CIK0000320193.json?a=space+value",
        )
        self.assertEqual(request.connect_timeout, 2.0)
        self.assertEqual(request.read_timeout, 3.0)
        self.assertNotIn("url", request.__dataclass_fields__)
        self.assertEqual(
            request.headers,
            {
                "Host": "data.sec.gov",
                "User-Agent": "OpenFundScore security@openfundscore.org",
            },
        )

    def test_request_headers_use_a_case_insensitive_allowlist_before_transport(
        self,
    ) -> None:
        response = HttpResponse(
            status=200,
            headers={"Content-Type": "application/json"},
            body=b"{}",
        )
        forbidden = (
            {"Host": "evil.test"},
            {"host": "evil.test"},
            {"Content-Length": "2"},
            {"Transfer-Encoding": "chunked"},
            {"Connection": "keep-alive"},
            {"TE": "trailers"},
            {"Trailer": "X-Hash"},
            {"Upgrade": "websocket"},
            {"Proxy-Authorization": "PRIVATE-HEADER-SENTINEL"},
            {"X-Unneeded": "value"},
            {"Accept": "application/json", "accept": "application/problem+json"},
            {"User-Agent": "safe", "user-agent": "conflict"},
        )
        for headers in forbidden:
            with self.subTest(headers=tuple(headers)):
                transport = RecordingTransport(response)
                client = FixedHostHttpClient(host="data.sec.gov", transport=transport)
                with self.assertRaises(ProviderHttpError) as raised:
                    client.get_json(path="/safe", query={}, headers=headers)
                self.assertEqual(raised.exception.code, "invalid_request")
                self.assertEqual(raised.exception.path, "$request.headers")
                self.assertNotIn("PRIVATE-HEADER-SENTINEL", str(raised.exception))
                self.assertEqual(transport.requests, [])

        transport = RecordingTransport(response)
        result = FixedHostHttpClient(
            host="data.sec.gov",
            transport=transport,
        ).get_json(
            path="/safe",
            query={},
            headers={"accept": "application/json", "USER-AGENT": "reviewed-client"},
        )
        self.assertEqual(result.document, {})
        self.assertEqual(
            transport.requests[0].headers,
            {
                "Host": "data.sec.gov",
                "Accept": "application/json",
                "User-Agent": "reviewed-client",
            },
        )

    def test_request_header_values_are_bounded_visible_ascii_pretransport(self) -> None:
        response = HttpResponse(
            status=200,
            headers={"Content-Type": "application/json"},
            body=b"{}",
        )
        transport = RecordingTransport(response)
        client = FixedHostHttpClient(host="data.sec.gov", transport=transport)

        client.get_json(
            path="/safe",
            query={},
            headers={"Accept": " " + ("a" * 1022) + "~"},
        )
        self.assertEqual(len(transport.requests), 1)

        for value in (
            "a" * 1025,
            "PRIVATE-HEADER-SENTINEL\x7f",
            "PRIVATE-HEADER-SENTINEL\x80",
            "PRIVATE-HEADER-SENTINELĀ",
            "PRIVATE-HEADER-SENTINEL\n",
        ):
            with (
                self.subTest(value_length=len(value)),
                self.assertRaises(ProviderHttpError) as raised,
            ):
                client.get_json(
                    path="/safe",
                    query={},
                    headers={"User-Agent": value},
                )
            self.assertEqual(raised.exception.code, "invalid_request")
            self.assertEqual(raised.exception.path, "$request.headers")
            self.assertNotIn("PRIVATE-HEADER-SENTINEL", str(raised.exception))
            self.assertIsNone(raised.exception.__cause__)
            self.assertIsNone(raised.exception.__context__)
        self.assertEqual(len(transport.requests), 1)

    def test_query_mapping_is_bounded_strict_utf8_and_redacted_pretransport(
        self,
    ) -> None:
        response = HttpResponse(
            status=200,
            headers={"Content-Type": "application/json"},
            body=b"{}",
        )
        transport = RecordingTransport(response)
        client = FixedHostHttpClient(host="data.sec.gov", transport=transport)
        client.get_json(
            path="/safe",
            query=MappingProxyType({"label": "基金"}),
            headers={},
        )
        self.assertEqual(transport.requests[0].target, "/safe?label=%E5%9F%BA%E9%87%91")

        class StrSubclass(str):
            pass

        invalid_queries = (
            {f"key-{index}": "value" for index in range(65)},
            {"k" * 1025: "value"},
            {"key": "v" * 1025},
            {"key": "é" * 1025},
            {"key": "PRIVATE-QUERY-SENTINEL\ud800"},
            {StrSubclass("key"): "value"},
            {"key": StrSubclass("value")},
        )
        for query in invalid_queries:
            with (
                self.subTest(query_size=len(query)),
                self.assertRaises(ProviderHttpError) as raised,
            ):
                client.get_json(path="/safe", query=query, headers={})
            self.assertEqual(raised.exception.code, "invalid_request")
            self.assertEqual(raised.exception.path, "$request.query")
            self.assertNotIn("PRIVATE-QUERY-SENTINEL", str(raised.exception))
            self.assertIsNone(raised.exception.__cause__)
            self.assertIsNone(raised.exception.__context__)
        self.assertEqual(len(transport.requests), 1)

    def test_hostile_query_mapping_failures_are_bounded_redacted_and_pretransport(
        self,
    ) -> None:
        class HostileMapping(Mapping[str, str]):
            def __init__(self, failure: BaseException) -> None:
                self.failure = failure

            def __getitem__(self, key: str) -> str:
                raise AssertionError("getitem must not be reached")

            def __iter__(self):
                raise AssertionError("iter must not be reached")

            def __len__(self) -> int:
                raise AssertionError("len must not be reached")

            def items(self):
                raise self.failure

        class EndlessMapping(Mapping[str, str]):
            yielded = 0

            def __getitem__(self, key: str) -> str:
                raise AssertionError("getitem must not be reached")

            def __iter__(self):
                raise AssertionError("iter must not be reached")

            def __len__(self) -> int:
                raise AssertionError("len must not be reached")

            def items(self):
                while True:
                    self.yielded += 1
                    yield f"key-{self.yielded}", "value"

        transport = RecordingTransport(
            HttpResponse(
                status=200,
                headers={"Content-Type": "application/json"},
                body=b"{}",
            )
        )
        client = FixedHostHttpClient(host="data.sec.gov", transport=transport)

        endless = EndlessMapping()
        for query in (
            HostileMapping(RuntimeError("PRIVATE-MAPPING-SENTINEL")),
            endless,
        ):
            with self.assertRaises(ProviderHttpError) as raised:
                client.get_json(path="/safe", query=query, headers={})
            self.assertEqual(raised.exception.code, "invalid_request")
            self.assertEqual(raised.exception.path, "$request.query")
            self.assertNotIn("PRIVATE-MAPPING-SENTINEL", str(raised.exception))
            self.assertIsNone(raised.exception.__cause__)
            self.assertIsNone(raised.exception.__context__)
        self.assertEqual(endless.yielded, 65)
        self.assertEqual(transport.requests, [])

        with self.assertRaises(KeyboardInterrupt):
            client.get_json(
                path="/safe",
                query=HostileMapping(KeyboardInterrupt()),
                headers={},
            )
        self.assertEqual(transport.requests, [])

    def test_urlencode_exceptions_are_redacted_but_base_exceptions_propagate(
        self,
    ) -> None:
        transport = RecordingTransport(
            HttpResponse(
                status=200,
                headers={"Content-Type": "application/json"},
                body=b"{}",
            )
        )
        client = FixedHostHttpClient(host="data.sec.gov", transport=transport)

        with (
            patch(
                "openfundscore.official_providers.urlencode",
                side_effect=RuntimeError("PRIVATE-URLENCODE-SENTINEL"),
            ),
            self.assertRaises(ProviderHttpError) as raised,
        ):
            client.get_json(path="/safe", query={"key": "value"}, headers={})
        self.assertEqual(raised.exception.code, "invalid_request")
        self.assertEqual(raised.exception.path, "$request.query")
        self.assertNotIn("PRIVATE-URLENCODE-SENTINEL", str(raised.exception))
        self.assertIsNone(raised.exception.__cause__)
        self.assertIsNone(raised.exception.__context__)
        self.assertEqual(transport.requests, [])

        with (
            patch(
                "openfundscore.official_providers.urlencode",
                side_effect=KeyboardInterrupt(),
            ),
            self.assertRaises(KeyboardInterrupt),
        ):
            client.get_json(path="/safe", query={"key": "value"}, headers={})
        self.assertEqual(transport.requests, [])

    def test_raw_path_and_request_target_accept_8192_and_reject_8193(self) -> None:
        response = HttpResponse(
            status=200,
            headers={"Content-Type": "application/json"},
            body=b"{}",
        )
        transport = RecordingTransport(response)
        client = FixedHostHttpClient(host="data.sec.gov", transport=transport)

        client.get_json(path="/" + ("a" * 8191), query={}, headers={})
        self.assertEqual(len(transport.requests[0].target.encode("utf-8")), 8192)

        with self.assertRaises(ProviderHttpError) as raised:
            client.get_json(path="/" + ("a" * 8192), query={}, headers={})
        self.assertEqual(raised.exception.code, "invalid_request")
        self.assertEqual(raised.exception.path, "$request.path")
        self.assertIsNone(raised.exception.__cause__)
        self.assertIsNone(raised.exception.__context__)
        self.assertEqual(len(transport.requests), 1)

    def test_nested_path_escapes_have_a_fixed_decode_budget_before_transport(
        self,
    ) -> None:
        response = HttpResponse(
            status=200,
            headers={"Content-Type": "application/json"},
            body=b"{}",
        )
        transport = RecordingTransport(response)
        client = FixedHostHttpClient(host="data.sec.gov", transport=transport)

        client.get_json(path="/safe/%41.txt", query={}, headers={})
        self.assertEqual(transport.requests[0].target, "/safe/%41.txt")

        for layers, expected_decode_calls in ((500, 8), (5000, 0)):
            nested = "/safe/%" + ("25" * layers) + "2e"
            with (
                self.subTest(layers=layers),
                patch("builtins.chr", wraps=chr) as decode_spy,
                self.assertRaises(ProviderHttpError) as raised,
            ):
                client.get_json(path=nested, query={}, headers={})
            self.assertEqual(raised.exception.code, "invalid_request")
            self.assertEqual(raised.exception.path, "$request.path")
            self.assertEqual(decode_spy.call_count, expected_decode_calls)
            self.assertIsNone(raised.exception.__cause__)
            self.assertIsNone(raised.exception.__context__)

        self.assertEqual(len(transport.requests), 1)

    def test_response_validation_rejects_untrusted_json_without_echoing_it(
        self,
    ) -> None:
        marker = b"PRIVATE-RESPONSE-SENTINEL"
        cases = (
            (500, {"Content-Type": "application/json"}, b"{}", "http_status"),
            (
                200,
                {"Content-Type": "text/html"},
                marker,
                "invalid_content_type",
            ),
            (
                200,
                {
                    "Content-Type": "application/json",
                    "content-type": "text/html",
                },
                marker,
                "transport_failure",
            ),
            (
                200,
                {"Content-Type": "application/json; charset=iso-8859-1"},
                b"{}",
                "invalid_content_type",
            ),
            (
                200,
                {"Content-Type": "application/json; charset=utf-8; charset=utf-8"},
                b"{}",
                "invalid_content_type",
            ),
            (
                200,
                {"Content-Type": "application/json"},
                b"\xff",
                "invalid_utf8",
            ),
            (
                200,
                {"Content-Type": "application/json"},
                b'{"a":1,"a":2}',
                "invalid_json",
            ),
            (
                200,
                {"Content-Type": "application/json"},
                b'{"a":NaN}',
                "invalid_json",
            ),
            (
                200,
                {"Content-Type": "application/json"},
                b'{"nested":[{"value":1e400}]}',
                "invalid_json",
            ),
            (
                200,
                {"Content-Type": "application/json"},
                (b'{"a":' * 70) + b"null" + (b"}" * 70),
                "json_too_complex",
            ),
            (
                200,
                {"Content-Type": "application/json"},
                b"[" + b",".join(b"0" for _ in range(101)) + b"]",
                "json_too_complex",
            ),
            (
                200,
                {"Content-Type": "application/json", "Content-Length": "9999"},
                b"{}",
                "invalid_content_length",
            ),
        )
        for status, headers, body, code in cases:
            with self.subTest(code=code):
                client = FixedHostHttpClient(
                    host="data.sec.gov",
                    transport=RecordingTransport(
                        HttpResponse(status=status, headers=headers, body=body)
                    ),
                    connect_timeout=2.0,
                    read_timeout=3.0,
                    max_response_bytes=4096,
                    max_json_depth=64,
                    max_container_items=100,
                    max_json_nodes=1000,
                )
                with self.assertRaises(ProviderHttpError) as raised:
                    client.get_json(path="/safe.json", query={}, headers={})
                self.assertEqual(raised.exception.code, code)
                self.assertNotIn(marker.decode(), str(raised.exception))
                self.assertIsNone(raised.exception.__cause__)
                self.assertIsNone(raised.exception.__context__)

    def test_content_type_accepts_only_json_media_types_with_strict_parameters(
        self,
    ) -> None:
        valid_values = (
            "application/json",
            "Application/JSON",
            "application/json; charset=utf-8",
            'application/problem+json; charset="UTF-8"',
            "text/vnd.example+json ; charset = utf-8",
            "x!#$%&'*+-.^_`|~/vnd.example+json",
        )
        for value in valid_values:
            with self.subTest(value=value):
                client = FixedHostHttpClient(
                    host="data.sec.gov",
                    transport=RecordingTransport(
                        HttpResponse(
                            status=200,
                            headers={"Content-Type": value},
                            body=b'{"ok":true}',
                        )
                    ),
                )

                self.assertEqual(
                    client.get_json(path="/safe.json", query={}, headers={}).document,
                    {"ok": True},
                )

    def test_content_type_rejects_invalid_or_ambiguous_values_without_echoing(
        self,
    ) -> None:
        marker = "PRIVATE-CONTENT-TYPE-SENTINEL"
        invalid_values = (
            None,
            "",
            "evil+json",
            "/problem+json",
            "text/+json",
            "application/+json",
            "application/json/extra",
            '"application/json"',
            "application/(problem)+json",
            "application/json;",
            "application/json; charset",
            "application/json; =utf-8",
            "application/json; charset=utf-8=evil",
            "application/json; charset=utf-8; CHARSET=utf-8",
            'application/json; charset="utf-8',
            'application/json; charset="utf-8"trailing',
            'application/json; charset="utf-8\\"',
            "application/json; charset=utf-8; boundary=safe",
            "application／problem+json",
            "application/problem＋json",
            f"application/json; charset={marker}",
        )
        for value in invalid_values:
            with self.subTest(value=value):
                headers = {} if value is None else {"Content-Type": value}
                client = FixedHostHttpClient(
                    host="data.sec.gov",
                    transport=RecordingTransport(
                        HttpResponse(status=200, headers=headers, body=b"{}")
                    ),
                )

                with self.assertRaises(ProviderHttpError) as raised:
                    client.get_json(path="/safe.json", query={}, headers={})

                self.assertEqual(raised.exception.code, "invalid_content_type")
                self.assertNotIn(marker, str(raised.exception))
                self.assertIsNone(raised.exception.__cause__)
                self.assertIsNone(raised.exception.__context__)

    def test_content_type_control_bytes_are_rejected_as_an_invalid_response(
        self,
    ) -> None:
        marker = "PRIVATE-CONTROL-SENTINEL"
        for value in (
            f"application/json\t; charset=utf-8{marker}",
            f"application/json\r{marker}",
            f"application/json\n{marker}",
            f"application/json\x00{marker}",
            f"application/json\x7f{marker}",
        ):
            with self.subTest(value=repr(value)):
                client = FixedHostHttpClient(
                    host="data.sec.gov",
                    transport=RecordingTransport(
                        HttpResponse(
                            status=200,
                            headers={"Content-Type": value},
                            body=b"{}",
                        )
                    ),
                )

                with self.assertRaises(ProviderHttpError) as raised:
                    client.get_json(path="/safe.json", query={}, headers={})

                self.assertEqual(raised.exception.code, "transport_failure")
                self.assertNotIn(marker, str(raised.exception))
                self.assertIsNone(raised.exception.__cause__)
                self.assertIsNone(raised.exception.__context__)

    def test_content_length_uses_a_strict_bounded_ascii_decimal_grammar(self) -> None:
        marker = "PRIVATE-CONTENT-LENGTH-SENTINEL"
        invalid_values = (
            "",
            "+2",
            "-2",
            " 2",
            "2 ",
            "１",
            "1, 2",
            marker,
            "9" * 5000,
        )
        for value in invalid_values:
            with self.subTest(value=value[:32]):
                client = FixedHostHttpClient(
                    host="data.sec.gov",
                    max_response_bytes=4096,
                    transport=RecordingTransport(
                        HttpResponse(
                            status=200,
                            headers={
                                "Content-Type": "application/json",
                                "Content-Length": value,
                            },
                            body=b"{}",
                        )
                    ),
                )
                with self.assertRaises(ProviderHttpError) as raised:
                    client.get_json(path="/safe.json", query={}, headers={})
                self.assertEqual(raised.exception.code, "invalid_content_length")
                self.assertNotIn(marker, str(raised.exception))
                self.assertNotIn("999999", str(raised.exception))
                self.assertIsNone(raised.exception.__cause__)
                self.assertIsNone(raised.exception.__context__)

    def test_content_length_must_exactly_match_the_injected_response_body(self) -> None:
        marker = "PRIVATE-CONTENT-LENGTH-MISMATCH"
        for declared_size in (0, 1, 3, 9999):
            with self.subTest(declared_size=declared_size):
                client = FixedHostHttpClient(
                    host="data.sec.gov",
                    max_response_bytes=4096,
                    transport=RecordingTransport(
                        HttpResponse(
                            status=200,
                            headers={
                                "Content-Type": "application/json",
                                "Content-Length": str(declared_size),
                                "X-Marker": marker,
                            },
                            body=b"{}",
                        )
                    ),
                )
                with self.assertRaises(ProviderHttpError) as raised:
                    client.get_json(path="/safe.json", query={}, headers={})
                self.assertEqual(raised.exception.code, "invalid_content_length")
                self.assertNotIn(marker, str(raised.exception))

        exact = FixedHostHttpClient(
            host="data.sec.gov",
            transport=RecordingTransport(
                HttpResponse(
                    status=200,
                    headers={
                        "Content-Type": "application/json",
                        "Content-Length": "2",
                    },
                    body=b"{}",
                )
            ),
        ).get_json(path="/safe.json", query={}, headers={})
        self.assertEqual(exact.document, {})

    def test_host_path_headers_and_limits_fail_closed_before_transport(self) -> None:
        response = HttpResponse(
            status=200,
            headers={"Content-Type": "application/json"},
            body=b"{}",
        )
        for host in ("http://data.sec.gov", "localhost", "127.0.0.1", "evil.test"):
            with self.subTest(host=host):
                with self.assertRaises(ProviderHttpError) as raised:
                    FixedHostHttpClient(
                        host=host,
                        allowed_hosts=frozenset({host}),
                        transport=RecordingTransport(response),
                    )
                self.assertEqual(raised.exception.code, "invalid_client_config")

        transport = RecordingTransport(response)
        client = FixedHostHttpClient(
            host="data.sec.gov",
            allowed_hosts=frozenset({"data.sec.gov"}),
            transport=transport,
        )
        for path in ("https://evil.test/x", "//evil.test/x", "/../x", "/x#fragment"):
            with self.subTest(path=path), self.assertRaises(ProviderHttpError):
                client.get_json(path=path, query={}, headers={})
        with self.assertRaises(ProviderHttpError):
            client.get_json(
                path="/safe",
                query={},
                headers={"X-Bad\r\nInjected": "yes"},
            )
        self.assertEqual(transport.requests, [])

    def test_encoded_path_confusion_is_rejected_before_transport(self) -> None:
        transport = RecordingTransport(
            HttpResponse(
                status=200,
                headers={"Content-Type": "application/json"},
                body=b"{}",
            )
        )
        client = FixedHostHttpClient(host="data.sec.gov", transport=transport)
        unsafe_paths = (
            "/safe/%2e%2e/private",
            "/safe/%2E%2E/private",
            "/safe/%252e%252e/private",
            "/safe/%252E%252E/private",
            "/safe/%2fprivate",
            "/safe/%2Fprivate",
            "/safe/%252fprivate",
            "/safe/%5cprivate",
            "/safe/%255Cprivate",
            "/safe/%00private",
            "/safe/%250dprivate",
            "/safe/%3fquery",
            "/safe/%2523fragment",
            "/safe/%",
            "/safe/%2",
            "/safe/%zz",
        )

        for path in unsafe_paths:
            with (
                self.subTest(path=path),
                self.assertRaises(ProviderHttpError) as raised,
            ):
                client.get_json(path=path, query={}, headers={})
            self.assertEqual(raised.exception.code, "invalid_request")
            self.assertEqual(raised.exception.path, "$request.path")

        self.assertEqual(transport.requests, [])

    def test_hostile_typed_boundaries_return_only_stable_http_errors(self) -> None:
        with self.assertRaises(ProviderHttpError) as config:
            FixedHostHttpClient(
                host="data.sec.gov",
                allowed_hosts=None,  # type: ignore[arg-type]
                transport=RecordingTransport(
                    HttpResponse(
                        status=200,
                        headers={"Content-Type": "application/json"},
                        body=b"{}",
                    )
                ),
            )
        self.assertEqual(config.exception.code, "invalid_client_config")
        client = FixedHostHttpClient(
            host="data.sec.gov",
            transport=RecordingTransport(
                HttpResponse(
                    status=200,
                    headers=None,  # type: ignore[arg-type]
                    body=b"PRIVATE-RESPONSE-SENTINEL",
                )
            ),
        )
        with self.assertRaises(ProviderHttpError) as response:
            client.get_json(path="/safe", query={}, headers={})
        self.assertEqual(response.exception.code, "transport_failure")
        self.assertNotIn("PRIVATE-RESPONSE-SENTINEL", str(response.exception))

    def test_timeouts_accept_60_and_reject_non_builtin_or_out_of_range_values(
        self,
    ) -> None:
        response = HttpResponse(
            status=200,
            headers={"Content-Type": "application/json"},
            body=b"{}",
        )
        transport = RecordingTransport(response)
        client = FixedHostHttpClient(
            host="data.sec.gov",
            transport=transport,
            connect_timeout=60,
            read_timeout=60.0,
        )
        client.get_json(path="/safe", query={}, headers={})
        self.assertEqual(transport.requests[0].connect_timeout, 60.0)
        self.assertEqual(transport.requests[0].read_timeout, 60.0)

        class FloatSubclass(float):
            pass

        for field in ("connect_timeout", "read_timeout"):
            for value in (
                60.000_001,
                61,
                1e308,
                0,
                -1,
                float("nan"),
                float("inf"),
                True,
                FloatSubclass(1.0),
                "1",
            ):
                with (
                    self.subTest(field=field, value=repr(value)),
                    self.assertRaises(ProviderHttpError) as raised,
                ):
                    FixedHostHttpClient(
                        host="data.sec.gov",
                        **{field: value},  # type: ignore[arg-type]
                    )
                self.assertEqual(raised.exception.code, "invalid_client_config")
                self.assertEqual(raised.exception.path, "$client")
                self.assertIsNone(raised.exception.__cause__)
                self.assertIsNone(raised.exception.__context__)

    def test_default_transport_uses_stdlib_https_with_separate_bounded_timeouts(
        self,
    ) -> None:
        calls: dict[str, object] = {}

        class Socket:
            def settimeout(self, value: float) -> None:
                calls["read_timeout"] = value

        class Response:
            status = 200

            def getheaders(self):
                return [("Content-Type", "application/json")]

            def read(self, amount: int) -> bytes:
                calls["read_amount"] = amount
                return b'{"ok":true}'

        class Connection:
            def __init__(self, host: str, *, timeout: float, context: object) -> None:
                calls["host"] = host
                calls["connect_timeout"] = timeout
                calls["context"] = context
                self.sock = Socket()

            def request(
                self,
                method: str,
                target: str,
                *,
                headers: dict[str, str],
            ) -> None:
                calls["request"] = (method, target, headers)

            def getresponse(self) -> Response:
                return Response()

            def close(self) -> None:
                calls["closed"] = True

        with patch(
            "openfundscore.official_providers.http.client.HTTPSConnection",
            Connection,
        ):
            client = FixedHostHttpClient(
                host="data.sec.gov",
                connect_timeout=2.0,
                read_timeout=3.0,
                max_response_bytes=128,
            )
            result = client.get_json(path="/safe.json", query={}, headers={})

        self.assertEqual(result.document, {"ok": True})
        self.assertEqual(calls["host"], "data.sec.gov")
        self.assertEqual(calls["connect_timeout"], 2.0)
        self.assertEqual(calls["read_timeout"], 3.0)
        self.assertEqual(calls["read_amount"], 129)
        self.assertEqual(
            calls["request"],
            ("GET", "/safe.json", {"Host": "data.sec.gov"}),
        )
        self.assertTrue(calls["closed"])

    def test_default_transport_freezes_and_validates_status_before_headers_or_body(
        self,
    ) -> None:
        def run(status_value: object) -> tuple[list[str], ProviderHttpError | None]:
            calls: list[str] = []

            class Socket:
                def settimeout(self, value: float) -> None:
                    calls.append("timeout")

            class Response:
                @property
                def status(self):
                    calls.append("status")
                    return status_value

                def getheaders(self):
                    calls.append("headers")
                    return [("Content-Type", "application/json")]

                def read(self, amount: int) -> bytes:
                    calls.append("body")
                    return b"{}"

            class Connection:
                def __init__(
                    self,
                    host: str,
                    *,
                    timeout: float,
                    context: object,
                ) -> None:
                    self.sock = Socket()

                def request(
                    self,
                    method: str,
                    target: str,
                    *,
                    headers: dict[str, str],
                ) -> None:
                    calls.append("request")

                def getresponse(self) -> Response:
                    calls.append("response")
                    return Response()

                def close(self) -> None:
                    calls.append("closed")

            error: ProviderHttpError | None = None
            with patch(
                "openfundscore.official_providers.http.client.HTTPSConnection",
                Connection,
            ):
                try:
                    FixedHostHttpClient(host="data.sec.gov").get_json(
                        path="/safe.json",
                        query={},
                        headers={},
                    )
                except ProviderHttpError as failure:
                    error = failure
            return calls, error

        success_calls, success_error = run(200)
        self.assertIsNone(success_error)
        self.assertEqual(success_calls.count("status"), 1)
        self.assertIn("headers", success_calls)
        self.assertIn("body", success_calls)

        failed_calls, failed_error = run(500)
        self.assertIsNotNone(failed_error)
        assert failed_error is not None
        self.assertEqual(failed_error.code, "http_status")
        self.assertEqual(failed_calls.count("status"), 1)
        self.assertNotIn("headers", failed_calls)
        self.assertNotIn("body", failed_calls)

        invalid_calls, invalid_error = run("PRIVATE-STATUS-SENTINEL")
        self.assertIsNotNone(invalid_error)
        assert invalid_error is not None
        self.assertEqual(invalid_error.code, "transport_failure")
        self.assertNotIn("PRIVATE-STATUS-SENTINEL", str(invalid_error))
        self.assertEqual(invalid_calls.count("status"), 1)
        self.assertNotIn("headers", invalid_calls)
        self.assertNotIn("body", invalid_calls)

    def test_default_transport_rejects_status_without_reading_response_body(
        self,
    ) -> None:
        def connection_type(status_code: int, calls: list[str]):
            class Socket:
                def settimeout(self, value: float) -> None:
                    calls.append("timeout")

            class Response:
                status = status_code

                def getheaders(self):
                    calls.append("headers")
                    return [("Content-Type", "text/plain")]

                def read(self, amount: int) -> bytes:
                    calls.append("PRIVATE-BODY-READ-MARKER")
                    raise AssertionError("non-success response body must not be read")

            class Connection:
                def __init__(
                    self,
                    host: str,
                    *,
                    timeout: float,
                    context: object,
                ) -> None:
                    self.sock = Socket()

                def request(
                    self,
                    method: str,
                    target: str,
                    *,
                    headers: dict[str, str],
                ) -> None:
                    calls.append("request")

                def getresponse(self) -> Response:
                    calls.append("response")
                    return Response()

                def close(self) -> None:
                    calls.append("closed")

            return Connection

        for status in (302, 404, 500):
            with self.subTest(status=status):
                calls: list[str] = []
                with (
                    patch(
                        "openfundscore.official_providers.http.client.HTTPSConnection",
                        connection_type(status, calls),
                    ),
                    self.assertRaises(ProviderHttpError) as raised,
                ):
                    FixedHostHttpClient(host="data.sec.gov").get_json(
                        path="/safe.json",
                        query={},
                        headers={},
                    )

                self.assertEqual(raised.exception.code, "http_status")
                self.assertNotIn("PRIVATE-BODY-READ-MARKER", calls)
                self.assertNotIn("headers", calls)
                self.assertIn("closed", calls)


SEC_FIXTURE = b"""{
  "cik": "0000320193",
  "name": "Example Issuer Inc.",
  "filings": {"recent": {
    "accessionNumber": ["0000320193-26-000001", "0000320193-26-000002"],
    "filingDate": ["2026-08-20", "2026-08-21"],
    "reportDate": ["2026-06-30", "2026-07-31"],
    "acceptanceDateTime": ["2026-08-20T18:30:00.000Z", "2026-08-21T12:00:00.000Z"],
    "form": ["10-Q", "8-K"],
    "primaryDocument": ["a10-q.htm", "a8-k.htm"]
  }}
}"""


class SecEdgarSubmissionsAdapterTests(unittest.TestCase):
    def test_sec_timezone_resolution_is_lazy_redacted_and_preserves_base_exceptions(
        self,
    ) -> None:
        cutoff = datetime(2026, 8, 21, 12, 30, tzinfo=UTC)
        with patch("openfundscore.official_providers.ZoneInfo") as zone_info:
            adapter = SecEdgarSubmissionsAdapter(
                user_agent="OpenFundScore security@openfundscore.org"
            )
            zone_info.assert_not_called()

        for failure in (
            ZoneInfoNotFoundError("PRIVATE-TZDB-SENTINEL"),
            RuntimeError("PRIVATE-TZDB-SENTINEL"),
        ):
            with (
                self.subTest(failure=type(failure).__name__),
                patch(
                    "openfundscore.official_providers.ZoneInfo",
                    side_effect=failure,
                ),
                patch.object(adapter, "_authorize_record"),
                self.assertRaises(ProviderHttpError) as raised,
            ):
                adapter.parse_submissions_fixture(
                    SEC_FIXTURE,
                    cik="0000320193",
                    fetched_at=cutoff,
                    evaluation_timestamp=cutoff,
                )
            self.assertEqual(raised.exception.code, "invalid_sec_payload")
            self.assertEqual(
                raised.exception.path,
                "$.filings.recent.acceptanceDateTime",
            )
            self.assertNotIn("PRIVATE-TZDB-SENTINEL", str(raised.exception))
            self.assertIsNone(raised.exception.__cause__)
            self.assertIsNone(raised.exception.__context__)

        with (
            patch(
                "openfundscore.official_providers.ZoneInfo",
                side_effect=KeyboardInterrupt(),
            ),
            patch.object(adapter, "_authorize_record"),
            self.assertRaises(KeyboardInterrupt),
        ):
            adapter.parse_submissions_fixture(
                SEC_FIXTURE,
                cik="0000320193",
                fetched_at=cutoff,
                evaluation_timestamp=cutoff,
            )

    def test_fetch_builds_valid_authorized_records_from_the_fixed_submissions_path(
        self,
    ) -> None:
        transport = RecordingTransport(
            HttpResponse(
                status=200,
                headers={"Content-Type": "application/json"},
                body=SEC_FIXTURE,
            )
        )
        now = datetime(2026, 8, 21, 12, 30, tzinfo=UTC)
        adapter = SecEdgarSubmissionsAdapter(
            user_agent="OpenFundScore security@openfundscore.org",
            transport=transport,
            clock=lambda: now,
        )

        with (
            patch(
                "openfundscore.official_providers.validate_record",
                wraps=validate_record,
            ) as validate_spy,
            patch(
                "openfundscore.official_providers.authorize_ingestion",
                wraps=__import__(
                    "openfundscore.provider_sdk",
                    fromlist=["authorize_ingestion"],
                ).authorize_ingestion,
            ) as authorize_spy,
        ):
            records = adapter.fetch_submissions(
                cik="0000320193",
                evaluation_timestamp=now,
            )

        self.assertEqual(validate_spy.call_count, 2)
        self.assertEqual(authorize_spy.call_count, 2)
        self.assertEqual(len(records), 2)
        self.assertEqual(
            transport.requests[0].target,
            "/submissions/CIK0000320193.json",
        )
        self.assertEqual(
            transport.requests[0].headers["User-Agent"],
            "OpenFundScore security@openfundscore.org",
        )
        first = records[0]
        self.assertEqual(first["provider_id"], "sec-edgar-submissions")
        self.assertEqual(first["entity_type"], "issuer")
        self.assertEqual(first["entity_id"], "sec:cik:0000320193")
        self.assertEqual(first["field"], "filing")
        self.assertEqual(first["value"]["name"], "Example Issuer Inc.")
        self.assertEqual(first["value"]["form"], "10-Q")
        self.assertEqual(first["value"]["filing_date"], "2026-08-20")
        self.assertEqual(first["value"]["report_date"], "2026-06-30")
        self.assertEqual(first["timezone"], "America/New_York; UTC acceptance")
        self.assertEqual(first["published_at"], "2026-08-20T18:30:00Z")
        self.assertEqual(first["fetched_at"], "2026-08-21T12:30:00Z")
        self.assertEqual(first["currency"], None)
        self.assertTrue(first["source_document_hash"].startswith("sha256:"))
        self.assertEqual(
            first["source_url"],
            "https://www.sec.gov/Archives/edgar/data/320193/"
            "000032019326000001/a10-q.htm",
        )
        self.assertEqual(first["rights"]["mode"], "derived_only")
        self.assertFalse(first["rights"]["redistribution_allowed"])

        entitlements = adapter.get_entitlements(evaluation_timestamp=now)
        self.assertEqual(entitlements.authentication_mode, AuthenticationMode.NONE)
        self.assertEqual(entitlements.source_type, SourceType.REGULATOR)
        self.assertEqual(entitlements.rights_mode, RightsMode.DERIVED_ONLY)
        self.assertEqual(entitlements.rate_limit.requests_per_period, 5)
        self.assertLessEqual(entitlements.rate_limit.requests_per_period, 10)
        self.assertEqual(
            entitlements.capabilities,
            frozenset(
                {
                    ProviderCapability.GET_DISCLOSURES,
                    ProviderCapability.GET_ENTITLEMENTS,
                }
            ),
        )

    def test_live_sec_rejects_explicit_evaluation_timestamp_before_any_call(
        self,
    ) -> None:
        class HostileTimezone(tzinfo):
            def utcoffset(self, value):
                raise RuntimeError("PRIVATE-EVALUATION-SENTINEL")

        invalid_values = (
            datetime(2026, 8, 21, 12, 30),  # noqa: DTZ001
            "2026-08-21T12:30:00Z",
            datetime(2026, 8, 21, 12, 30, tzinfo=HostileTimezone()),
        )
        for value in invalid_values:
            with self.subTest(value=type(value).__name__):
                transport = RecordingTransport(
                    HttpResponse(
                        status=200,
                        headers={"Content-Type": "application/json"},
                        body=SEC_FIXTURE,
                    )
                )
                adapter = SecEdgarSubmissionsAdapter(
                    user_agent="OpenFundScore security@openfundscore.org",
                    transport=transport,
                )
                with (
                    patch.object(LocalRateLimiter, "acquire", autospec=True) as acquire,
                    self.assertRaises(ProviderHttpError) as raised,
                ):
                    adapter.fetch_submissions(
                        cik="0000320193",
                        evaluation_timestamp=value,  # type: ignore[arg-type]
                    )
                self.assertEqual(raised.exception.code, "invalid_evaluation_timestamp")
                self.assertEqual(raised.exception.path, "$request.evaluation_timestamp")
                self.assertNotIn("PRIVATE-EVALUATION-SENTINEL", str(raised.exception))
                self.assertIsNone(raised.exception.__cause__)
                self.assertIsNone(raised.exception.__context__)
                acquire.assert_not_called()
                self.assertEqual(transport.requests, [])

        class InterruptingTimezone(tzinfo):
            def utcoffset(self, value):
                raise KeyboardInterrupt("PRIVATE-EVALUATION-INTERRUPT")

        transport = RecordingTransport(
            HttpResponse(
                status=200,
                headers={"Content-Type": "application/json"},
                body=SEC_FIXTURE,
            )
        )
        adapter = SecEdgarSubmissionsAdapter(
            user_agent="OpenFundScore security@openfundscore.org",
            transport=transport,
        )
        with (
            patch.object(LocalRateLimiter, "acquire", autospec=True) as acquire,
            self.assertRaises(KeyboardInterrupt),
        ):
            adapter.fetch_submissions(
                cik="0000320193",
                evaluation_timestamp=datetime(
                    2026,
                    8,
                    21,
                    12,
                    30,
                    tzinfo=InterruptingTimezone(),
                ),
            )
        acquire.assert_not_called()
        self.assertEqual(transport.requests, [])

    def test_live_sec_freezes_explicit_evaluation_timestamp_before_transport(
        self,
    ) -> None:
        timezone_active = [True]

        class ExpiringTimezone(tzinfo):
            def utcoffset(self, value):
                if not timezone_active[0]:
                    raise RuntimeError("PRIVATE-EXPIRED-TIMEZONE")
                return timedelta(hours=8)

        requests: list[HttpRequest] = []

        def transport(request: HttpRequest) -> HttpResponse:
            requests.append(request)
            timezone_active[0] = False
            return HttpResponse(
                status=200,
                headers={"Content-Type": "application/json"},
                body=SEC_FIXTURE,
            )

        cutoff = datetime(2026, 8, 21, 20, 30, tzinfo=ExpiringTimezone())
        adapter = SecEdgarSubmissionsAdapter(
            user_agent="OpenFundScore security@openfundscore.org",
            transport=transport,
            clock=lambda: datetime(2026, 8, 21, 12, 30, tzinfo=UTC),
        )

        records = adapter.fetch_submissions(
            cik="0000320193",
            evaluation_timestamp=cutoff,
        )

        self.assertEqual(len(requests), 1)
        self.assertEqual(len(records), 2)
        self.assertEqual(records[0]["fetched_at"], "2026-08-21T12:30:00Z")

    def test_sec_acceptance_datetime_uses_extended_ascii_rfc3339_utc(self) -> None:
        adapter = SecEdgarSubmissionsAdapter(
            user_agent="OpenFundScore security@openfundscore.org"
        )
        cutoff = datetime(2026, 8, 21, 12, 30, tzinfo=UTC)

        for value in (
            "2026-08-20T18:30:00Z",
            "2026-08-20T18:30:00.0Z",
            "2026-08-20T18:30:00.000000Z",
        ):
            with self.subTest(valid=value):
                document = json.loads(SEC_FIXTURE)
                document["filings"]["recent"]["acceptanceDateTime"][0] = value
                records = adapter.parse_submissions_fixture(
                    json.dumps(document).encode(),
                    cik="0000320193",
                    fetched_at=cutoff,
                    evaluation_timestamp=cutoff,
                )
                self.assertEqual(records[0]["published_at"], "2026-08-20T18:30:00Z")

        invalid_values = (
            "20260820T183000Z",
            "２０２６-08-20T18:30:00Z",
            "2026-０8-20T18:30:00Z",
            "2026-08-20T18:30:00+00:00",
            "2026-08-20 18:30:00Z",
            "2026-08-20t18:30:00Z",
            "2026-08-20T18:30:00z",
            "2026-08-20T18:30:00",
            "2026-08-20T18:30:00.Z",
            "2026-08-20T18:30:00.0000000Z",
            "2026-08-20T18:30:00,000Z",
        )
        for value in invalid_values:
            with self.subTest(invalid=value):
                document = json.loads(SEC_FIXTURE)
                document["filings"]["recent"]["acceptanceDateTime"][0] = value
                with self.assertRaises(ProviderHttpError) as raised:
                    adapter.parse_submissions_fixture(
                        json.dumps(document).encode(),
                        cik="0000320193",
                        fetched_at=cutoff,
                        evaluation_timestamp=cutoff,
                    )
                self.assertEqual(raised.exception.code, "invalid_sec_payload")
                self.assertNotIn(value, str(raised.exception))
                self.assertIsNone(raised.exception.__cause__)
                self.assertIsNone(raised.exception.__context__)

    def test_sec_report_date_is_ascii_and_no_later_than_filing_date(self) -> None:
        adapter = SecEdgarSubmissionsAdapter(
            user_agent="OpenFundScore security@openfundscore.org"
        )
        cutoff = datetime(2026, 8, 21, 12, 30, tzinfo=UTC)

        equal = json.loads(SEC_FIXTURE)
        equal["filings"]["recent"]["reportDate"][0] = "2026-08-20"
        records = adapter.parse_submissions_fixture(
            json.dumps(equal).encode(),
            cik="0000320193",
            fetched_at=cutoff,
            evaluation_timestamp=cutoff,
        )
        self.assertEqual(records[0]["value"]["report_date"], "2026-08-20")

        for value in ("2026-08-21", "9999-12-31", "２０２６-06-30"):
            with self.subTest(value=value):
                document = json.loads(SEC_FIXTURE)
                document["filings"]["recent"]["reportDate"][0] = value
                with self.assertRaises(ProviderHttpError) as raised:
                    adapter.parse_submissions_fixture(
                        json.dumps(document).encode(),
                        cik="0000320193",
                        fetched_at=cutoff,
                        evaluation_timestamp=cutoff,
                    )
                self.assertEqual(raised.exception.code, "invalid_sec_payload")
                self.assertNotIn(value, str(raised.exception))
                self.assertIsNone(raised.exception.__cause__)
                self.assertIsNone(raised.exception.__context__)

    def test_sec_inputs_rows_and_future_knowledge_fail_closed_and_redacted(
        self,
    ) -> None:
        marker = "PRIVATE-USER-AGENT-SENTINEL"
        for user_agent in (
            "Python-urllib/3",
            f"Tool {marker}",
            "Tool user@example.com",
            "Tool user@example.org",
            "Tool user@example.net",
            "Tool user@sub.example.com",
            "Tool user@domain.invalid",
            "Tool user@sub.domain.test",
            "Tool user@domain.example",
            "Tool user@foo.localhost",
            "Tool user@DOMAIN.INVALID",
            "Tool user@localhost",
            "Tool user@127.0.0.1",
            "Tool user@intranet",
            "Tool user@-bad.example",
            "Tool user@bad-.example",
            "Tool user@bad..example",
            "Tool user@openfundscore。org",
            "security@openfundscore.org",
            "!! security@openfundscore.org",
            "A security@openfundscore.org",
            "curl/8.0 security@openfundscore.org",
            "Python-urllib/3 security@openfundscore.org",
            "Mozilla/5.0 security@openfundscore.org",
        ):
            with self.subTest(user_agent=user_agent):
                with self.assertRaises(ProviderHttpError) as raised:
                    SecEdgarSubmissionsAdapter(user_agent=user_agent)
                self.assertEqual(raised.exception.code, "invalid_user_agent")
                self.assertNotIn(marker, str(raised.exception))

        now = datetime(2026, 8, 21, 12, 30, tzinfo=UTC)
        for cik in ("320193", "００００３２０１９３", "0000320193/../x"):
            with self.subTest(cik=cik):
                transport = RecordingTransport(
                    HttpResponse(
                        status=200,
                        headers={"Content-Type": "application/json"},
                        body=SEC_FIXTURE,
                    )
                )
                adapter = SecEdgarSubmissionsAdapter(
                    user_agent="OpenFundScore security@openfundscore.org",
                    transport=transport,
                    clock=lambda: now,
                )
                with self.assertRaises(ProviderHttpError) as raised:
                    adapter.fetch_submissions(cik=cik, evaluation_timestamp=now)
                self.assertEqual(raised.exception.code, "invalid_cik")
                self.assertEqual(transport.requests, [])

        malformed_documents: list[dict] = []
        mismatched = json.loads(SEC_FIXTURE)
        mismatched["filings"]["recent"]["form"].pop()
        malformed_documents.append(mismatched)
        path_injection = json.loads(SEC_FIXTURE)
        path_injection["filings"]["recent"]["primaryDocument"][0] = "../private"
        malformed_documents.append(path_injection)
        wrong_cik = json.loads(SEC_FIXTURE)
        wrong_cik["cik"] = "999999"
        malformed_documents.append(wrong_cik)
        overlong_cik = json.loads(SEC_FIXTURE)
        overlong_cik["cik"] = "000000320193"
        malformed_documents.append(overlong_cik)
        wrong_accession_cik = json.loads(SEC_FIXTURE)
        wrong_accession_cik["filings"]["recent"]["accessionNumber"][0] = (
            "0000000001-26-000001"
        )
        malformed_documents.append(wrong_accession_cik)
        future = json.loads(SEC_FIXTURE)
        future["filings"]["recent"]["acceptanceDateTime"][0] = (
            "2026-08-22T00:00:00.000Z"
        )
        malformed_documents.append(future)
        impossible_eastern_filing_date = json.loads(SEC_FIXTURE)
        impossible_eastern_filing_date["filings"]["recent"]["filingDate"][0] = (
            "2026-08-21"
        )
        impossible_eastern_filing_date["filings"]["recent"]["acceptanceDateTime"][0] = (
            "2026-08-21T00:30:00.000Z"
        )
        malformed_documents.append(impossible_eastern_filing_date)
        compact_filing_date = json.loads(SEC_FIXTURE)
        compact_filing_date["filings"]["recent"]["filingDate"][0] = "20260820"
        malformed_documents.append(compact_filing_date)
        compact_report_date = json.loads(SEC_FIXTURE)
        compact_report_date["filings"]["recent"]["reportDate"][0] = "20260630"
        malformed_documents.append(compact_report_date)

        for document in malformed_documents:
            with self.subTest(document=document):
                transport = RecordingTransport(
                    HttpResponse(
                        status=200,
                        headers={"Content-Type": "application/json"},
                        body=json.dumps(document).encode(),
                    )
                )
                adapter = SecEdgarSubmissionsAdapter(
                    user_agent="OpenFundScore security@openfundscore.org",
                    transport=transport,
                    clock=lambda: now,
                )
                with self.assertRaises(ProviderHttpError) as raised:
                    adapter.fetch_submissions(
                        cik="0000320193",
                        evaluation_timestamp=now,
                    )
                self.assertEqual(raised.exception.code, "invalid_sec_payload")
                self.assertNotIn("../private", str(raised.exception))

    def test_sec_constructor_classifies_non_callable_clock_as_client_config(
        self,
    ) -> None:
        with self.assertRaises(ProviderHttpError) as raised:
            SecEdgarSubmissionsAdapter(
                user_agent="OpenFundScore security@openfundscore.org",
                clock=object(),  # type: ignore[arg-type]
            )

        self.assertEqual(raised.exception.code, "invalid_client_config")
        self.assertEqual(raised.exception.path, "$client.clock")

    def test_local_rate_limiter_enforces_even_spacing_and_ten_per_second_ceiling(
        self,
    ) -> None:
        current = [0.0]
        sleeps: list[float] = []

        def monotonic() -> float:
            return current[0]

        def sleep(seconds: float) -> None:
            sleeps.append(seconds)
            current[0] += seconds

        limiter = LocalRateLimiter(
            requests_per_second=5,
            monotonic=monotonic,
            sleep=sleep,
        )
        limiter.acquire()
        limiter.acquire()
        self.assertEqual(sleeps, [0.2])

        for invalid in (0, 11, True):
            with self.subTest(invalid=invalid), self.assertRaises(ProviderHttpError):
                LocalRateLimiter(requests_per_second=invalid)  # type: ignore[arg-type]

    def test_local_rate_limiter_validates_injected_callables_at_construction(
        self,
    ) -> None:
        for field, arguments in (
            ("monotonic", {"monotonic": object()}),
            ("sleep", {"sleep": object()}),
        ):
            with (
                self.subTest(field=field),
                self.assertRaises(ProviderHttpError) as raised,
            ):
                LocalRateLimiter(
                    requests_per_second=5,
                    **arguments,  # type: ignore[arg-type]
                )
            self.assertEqual(raised.exception.code, "invalid_client_config")
            self.assertEqual(
                raised.exception.path,
                f"$client.rate_limit.{field}",
            )

    def test_local_rate_limiter_does_not_swallow_base_exceptions(self) -> None:
        def interrupt() -> float:
            raise KeyboardInterrupt("PRIVATE-INTERRUPT-SENTINEL")

        with self.assertRaises(KeyboardInterrupt):
            LocalRateLimiter(
                requests_per_second=5,
                monotonic=interrupt,
            ).acquire()

        times = iter((0.0, 0.0))

        def stop(_: float) -> None:
            raise SystemExit("PRIVATE-EXIT-SENTINEL")

        limiter = LocalRateLimiter(
            requests_per_second=5,
            monotonic=lambda: next(times),
            sleep=stop,
        )
        limiter.acquire()
        with self.assertRaises(SystemExit):
            limiter.acquire()

    def test_local_rate_limiter_rejects_bad_clocks_and_redacts_failures(self) -> None:
        marker = "PRIVATE-LIMITER-SENTINEL"
        invalid_values = (True, False, float("nan"), float("inf"), float("-inf"), "0")
        for value in invalid_values:
            with self.subTest(value=repr(value)):
                limiter = LocalRateLimiter(
                    requests_per_second=5,
                    monotonic=lambda value=value: value,  # type: ignore[return-value]
                )
                with self.assertRaises(ProviderHttpError) as raised:
                    limiter.acquire()
                self.assertEqual(raised.exception.code, "rate_limiter_failure")
                self.assertNotIn(marker, str(raised.exception))
                self.assertIsNone(raised.exception.__cause__)
                self.assertIsNone(raised.exception.__context__)

        def broken_clock() -> float:
            raise RuntimeError(marker)

        with self.assertRaises(ProviderHttpError) as clock_failure:
            LocalRateLimiter(
                requests_per_second=5,
                monotonic=broken_clock,
            ).acquire()
        self.assertEqual(clock_failure.exception.code, "rate_limiter_failure")
        self.assertNotIn(marker, str(clock_failure.exception))

        times = iter((0.0, 0.0))

        def broken_sleep(_: float) -> None:
            raise RuntimeError(marker)

        limiter = LocalRateLimiter(
            requests_per_second=5,
            monotonic=lambda: next(times),
            sleep=broken_sleep,
        )
        limiter.acquire()
        with self.assertRaises(ProviderHttpError) as sleep_failure:
            limiter.acquire()
        self.assertEqual(sleep_failure.exception.code, "rate_limiter_failure")
        self.assertNotIn(marker, str(sleep_failure.exception))

    def test_local_rate_limiter_fails_closed_when_sleep_does_not_reach_deadline(
        self,
    ) -> None:
        sleep_calls: list[float] = []
        limiter = LocalRateLimiter(
            requests_per_second=5,
            monotonic=lambda: 0.0,
            sleep=sleep_calls.append,
        )
        limiter.acquire()
        with self.assertRaises(ProviderHttpError) as raised:
            limiter.acquire()
        self.assertEqual(raised.exception.code, "rate_limiter_failure")
        self.assertGreater(len(sleep_calls), 1)
        self.assertLessEqual(len(sleep_calls), 16)

    def test_adapters_accept_only_trusted_bounded_local_rate_limiters(self) -> None:
        class DuckLimiter:
            def __init__(self, requests_per_second: int) -> None:
                self.requests_per_second = requests_per_second

            def acquire(self) -> None:
                raise AssertionError("untrusted limiter must never run")

        constructors = (
            lambda limiter: SecEdgarSubmissionsAdapter(
                user_agent="OpenFundScore security@openfundscore.org",
                limiter=limiter,
            ),
            lambda limiter: WorldBankIndicatorsAdapter(
                countries=frozenset({"US"}),
                limiter=limiter,
            ),
        )
        for constructor in constructors:
            for requests_per_second in (5, 1000):
                with self.subTest(
                    constructor=constructor,
                    requests_per_second=requests_per_second,
                ):
                    with self.assertRaises(ProviderHttpError) as raised:
                        constructor(DuckLimiter(requests_per_second))
                    self.assertEqual(raised.exception.code, "invalid_client_config")

        damaged = LocalRateLimiter(requests_per_second=5)
        del damaged._monotonic
        with self.assertRaises(ProviderHttpError) as raised:
            WorldBankIndicatorsAdapter(
                countries=frozenset({"US"}),
                limiter=damaged,
            )
        self.assertEqual(raised.exception.code, "invalid_client_config")
        self.assertIsNone(raised.exception.__cause__)
        self.assertIsNone(raised.exception.__context__)

        current = [0.0]
        sleeps: list[float] = []

        def monotonic() -> float:
            return current[0]

        def sleep(seconds: float) -> None:
            sleeps.append(seconds)
            current[0] += seconds

        limiter = LocalRateLimiter(
            requests_per_second=10,
            monotonic=monotonic,
            sleep=sleep,
        )
        adapter = WorldBankIndicatorsAdapter(
            countries=frozenset({"US"}),
            limiter=limiter,
        )
        limiter.acquire()
        limiter.acquire()
        self.assertEqual(sleeps, [0.1])
        entitlements = adapter.get_entitlements(
            evaluation_timestamp=datetime(2026, 8, 21, 12, 30, tzinfo=UTC)
        )
        self.assertEqual(entitlements.rate_limit.requests_per_period, 10)
        self.assertEqual(entitlements.rate_limit.period_seconds, 1)
        self.assertEqual(entitlements.rate_limit.burst, 1)

    def test_adapter_limiter_spacing_ignores_injected_alias_mutation(self) -> None:
        current = [0.0]
        sleeps: list[float] = []

        def monotonic() -> float:
            return current[0]

        def sleep(seconds: float) -> None:
            sleeps.append(seconds)
            current[0] += seconds

        injected = LocalRateLimiter(
            requests_per_second=2,
            monotonic=monotonic,
            sleep=sleep,
        )
        injected._interval = 0.001
        adapter = WorldBankIndicatorsAdapter(
            countries=frozenset({"US"}),
            limiter=injected,
        )
        self.assertIsNot(adapter._limiter, injected)

        injected.requests_per_second = 10
        injected._interval = 0.0001
        injected._monotonic = lambda: float("nan")
        injected._sleep = lambda _: None
        adapter._limiter.acquire()
        adapter._limiter.acquire()

        self.assertEqual(sleeps, [0.5])
        entitlements = adapter.get_entitlements(
            evaluation_timestamp=datetime(2026, 8, 21, 12, 30, tzinfo=UTC)
        )
        self.assertEqual(entitlements.rate_limit.requests_per_period, 2)

    def test_offline_fixture_parse_uses_the_same_validation_authorization_boundary(
        self,
    ) -> None:
        now = datetime(2026, 8, 21, 12, 30, tzinfo=UTC)
        adapter = SecEdgarSubmissionsAdapter(
            user_agent="OpenFundScore security@openfundscore.org",
        )
        records = adapter.parse_submissions_fixture(
            SEC_FIXTURE,
            cik="0000320193",
            fetched_at=now,
            evaluation_timestamp=now,
        )
        self.assertEqual(len(records), 2)
        self.assertEqual(
            records[0]["provider_record_id"], "sec:0000320193:0000320193-26-000001"
        )

    def test_fixture_rejects_hostile_explicit_timestamps_with_stable_errors(
        self,
    ) -> None:
        class HostileTimezone(tzinfo):
            def utcoffset(self, value):
                raise RuntimeError("PRIVATE-TIMESTAMP-SENTINEL")

        now = datetime(2026, 8, 21, 12, 30, tzinfo=UTC)
        naive = datetime(2026, 8, 21, 12, 30)  # noqa: DTZ001
        hostile = datetime(2026, 8, 21, 12, 30, tzinfo=HostileTimezone())
        adapter = SecEdgarSubmissionsAdapter(
            user_agent="OpenFundScore security@openfundscore.org",
        )
        for fetched_at, evaluation_timestamp, expected_code in (
            (naive, now, "invalid_fetched_at"),
            (now, naive, "invalid_evaluation_timestamp"),
            (hostile, now, "invalid_fetched_at"),
            (now, hostile, "invalid_evaluation_timestamp"),
        ):
            with self.subTest(expected_code=expected_code):
                with self.assertRaises(ProviderHttpError) as raised:
                    adapter.parse_submissions_fixture(
                        SEC_FIXTURE,
                        cik="0000320193",
                        fetched_at=fetched_at,
                        evaluation_timestamp=evaluation_timestamp,
                    )
                self.assertEqual(raised.exception.code, expected_code)
                self.assertNotIn("PRIVATE-TIMESTAMP-SENTINEL", str(raised.exception))

    def test_live_sec_fetch_uses_its_post_response_clock_when_cutoff_is_omitted(
        self,
    ) -> None:
        now = datetime(2026, 8, 21, 12, 30, 0, 123456, tzinfo=UTC)
        adapter = SecEdgarSubmissionsAdapter(
            user_agent="OpenFundScore security@openfundscore.org",
            transport=RecordingTransport(
                HttpResponse(
                    status=200,
                    headers={"Content-Type": "application/json"},
                    body=SEC_FIXTURE,
                )
            ),
            clock=lambda: now,
        )
        records = adapter.fetch_submissions(cik="0000320193")
        self.assertTrue(
            all(
                record["fetched_at"] == "2026-08-21T12:30:00.123456Z"
                for record in records
            )
        )

    def test_live_sec_fetch_rejects_hostile_clock_values_with_a_redacted_error(
        self,
    ) -> None:
        class HostileTimezone(tzinfo):
            def utcoffset(self, value):
                raise RuntimeError("PRIVATE-CLOCK-SENTINEL")

        naive = datetime(2026, 8, 21, 12, 30)  # noqa: DTZ001
        clock_values = (
            None,
            "PRIVATE-CLOCK-SENTINEL",
            naive,
            datetime(2026, 8, 21, 12, 30, tzinfo=HostileTimezone()),
        )
        for clock_value in clock_values:
            with self.subTest(clock_value=type(clock_value).__name__):
                adapter = SecEdgarSubmissionsAdapter(
                    user_agent="OpenFundScore security@openfundscore.org",
                    transport=RecordingTransport(
                        HttpResponse(
                            status=200,
                            headers={"Content-Type": "application/json"},
                            body=SEC_FIXTURE,
                        )
                    ),
                    clock=lambda value=clock_value: value,  # type: ignore[return-value]
                )
                with self.assertRaises(ProviderHttpError) as raised:
                    adapter.fetch_submissions(cik="0000320193")
                self.assertEqual(raised.exception.code, "invalid_clock")
                self.assertNotIn("PRIVATE-CLOCK-SENTINEL", str(raised.exception))


WORLD_BANK_PAGE_1 = [
    {
        "page": 1,
        "pages": 2,
        "per_page": 1,
        "total": 2,
        "sourceid": "2",
        "lastupdated": "2026-08-20",
    },
    [
        {
            "indicator": {"id": "NY.GDP.MKTP.CD", "value": "GDP (current US$)"},
            "country": {"id": "US", "value": "United States"},
            "countryiso3code": "USA",
            "date": "2024",
            "value": 100.5,
            "unit": "current US$",
            "decimal": 0,
        }
    ],
]
WORLD_BANK_PAGE_2 = [
    {
        "page": 2,
        "pages": 2,
        "per_page": 1,
        "total": 2,
        "sourceid": "2",
        "lastupdated": "2026-08-20",
    },
    [
        {
            "indicator": {"id": "NY.GDP.MKTP.CD", "value": "GDP (current US$)"},
            "country": {"id": "US", "value": "United States"},
            "countryiso3code": "USA",
            "date": "2023",
            "value": None,
            "unit": "current US$",
            "decimal": 0,
        }
    ],
]


class WorldBankIndicatorsAdapterTests(unittest.TestCase):
    def test_world_bank_constructor_classifies_non_callable_clock_separately(
        self,
    ) -> None:
        with self.assertRaises(ProviderHttpError) as raised:
            WorldBankIndicatorsAdapter(
                countries=frozenset({"US"}),
                clock=object(),  # type: ignore[arg-type]
            )

        self.assertEqual(raised.exception.code, "invalid_client_config")
        self.assertEqual(raised.exception.path, "$client.clock")

    def test_explicit_evaluation_timestamp_is_rejected_before_transport(self) -> None:
        class HostileTimezone(tzinfo):
            def utcoffset(self, value):
                raise RuntimeError("PRIVATE-EVALUATION-SENTINEL")

        invalid_values = (
            datetime(2026, 8, 21, 12, 30),  # noqa: DTZ001
            "2026-08-21T12:30:00Z",
            datetime(2026, 8, 21, 12, 30, tzinfo=HostileTimezone()),
        )
        for value in invalid_values:
            with self.subTest(value=type(value).__name__):
                transport = RecordingTransport(
                    HttpResponse(
                        status=200,
                        headers={"Content-Type": "application/json"},
                        body=json.dumps(WORLD_BANK_PAGE_1).encode(),
                    )
                )
                adapter = WorldBankIndicatorsAdapter(
                    countries=frozenset({"US"}),
                    transport=transport,
                )
                with self.assertRaises(ProviderHttpError) as raised:
                    adapter.fetch_series(
                        country="US",
                        indicator="NY.GDP.MKTP.CD",
                        source=2,
                        per_page=1,
                        max_pages=2,
                        evaluation_timestamp=value,  # type: ignore[arg-type]
                    )
                self.assertEqual(
                    raised.exception.code,
                    "invalid_evaluation_timestamp",
                )
                self.assertEqual(transport.requests, [])
                self.assertNotIn("PRIVATE-EVALUATION-SENTINEL", str(raised.exception))

    def test_fetch_paginates_and_builds_authorized_macro_observations(self) -> None:
        transport = QueueTransport(
            [
                HttpResponse(
                    status=200,
                    headers={"Content-Type": "application/json"},
                    body=json.dumps(WORLD_BANK_PAGE_1).encode(),
                ),
                HttpResponse(
                    status=200,
                    headers={"Content-Type": "application/json"},
                    body=json.dumps(WORLD_BANK_PAGE_2).encode(),
                ),
            ]
        )
        now = datetime(2026, 8, 21, 12, 30, tzinfo=UTC)
        monotonic_values = iter((0.0, 1.0))
        adapter = WorldBankIndicatorsAdapter(
            countries=frozenset({"US"}),
            transport=transport,
            clock=lambda: now,
            limiter=LocalRateLimiter(
                requests_per_second=5,
                monotonic=lambda: next(monotonic_values),
                sleep=lambda _: self.fail("unexpected limiter sleep"),
            ),
        )

        with (
            patch(
                "openfundscore.official_providers.validate_record",
                wraps=validate_record,
            ) as validate_spy,
            patch(
                "openfundscore.official_providers.authorize_ingestion",
                wraps=__import__(
                    "openfundscore.provider_sdk",
                    fromlist=["authorize_ingestion"],
                ).authorize_ingestion,
            ) as authorize_spy,
        ):
            records = adapter.fetch_series(
                country="US",
                indicator="NY.GDP.MKTP.CD",
                source=2,
                per_page=1,
                max_pages=2,
                evaluation_timestamp=now,
            )

        self.assertEqual(validate_spy.call_count, 2)
        self.assertEqual(authorize_spy.call_count, 2)
        self.assertEqual(len(records), 2)
        self.assertEqual(
            [request.target for request in transport.requests],
            [
                (
                    "/v2/country/US/indicator/NY.GDP.MKTP.CD?"
                    "format=json&page=1&per_page=1&source=2"
                ),
                (
                    "/v2/country/US/indicator/NY.GDP.MKTP.CD?"
                    "format=json&page=2&per_page=1&source=2"
                ),
            ],
        )
        first, second = records
        self.assertEqual(first["entity_type"], "macro_observation")
        self.assertEqual(first["entity_id"], "wb:2:US:NY.GDP.MKTP.CD")
        self.assertEqual(first["period"], "2024")
        self.assertEqual(first["frequency"], "annual")
        self.assertEqual(first["timezone"], "UTC")
        self.assertEqual(first["unit"], "current US$")
        self.assertEqual(first["currency"], "USD")
        self.assertEqual(first["vintage"], "2026-08-20")
        self.assertEqual(
            first["publication_lag"],
            "Unknown: API lastupdated is date-only and does not expose observation publication time",
        )
        self.assertEqual(first["published_at"], "2026-08-21T12:30:00Z")
        self.assertEqual(first["value"]["value"], 100.5)
        self.assertEqual(first["value"]["decimal"], 0)
        self.assertEqual(first["value"]["country"]["iso3"], "USA")
        self.assertEqual(first["value"]["source"]["id"], "2")
        self.assertEqual(
            first["value"]["source"]["dataset"],
            "World Development Indicators",
        )
        self.assertIsNone(second["value"]["value"])
        self.assertEqual(second["quality_state"], "missing")
        self.assertEqual(first["point_in_time_status"], "not_point_in_time")
        self.assertEqual(first["rights"]["mode"], "derived_only")
        self.assertFalse(first["rights"]["redistribution_allowed"])

        entitlements = adapter.get_entitlements(evaluation_timestamp=now)
        self.assertEqual(entitlements.authentication_mode, AuthenticationMode.NONE)
        self.assertEqual(
            entitlements.source_type,
            SourceType.INDEX_OR_MACRO_OFFICIAL_SOURCE,
        )
        self.assertEqual(entitlements.rights_mode, RightsMode.DERIVED_ONLY)
        self.assertEqual(entitlements.source_ids, frozenset({"2"}))
        self.assertEqual(
            entitlements.dataset_ids,
            frozenset({"World Development Indicators"}),
        )
        self.assertEqual(
            entitlements.capabilities,
            frozenset(
                {
                    ProviderCapability.GET_ENTITLEMENTS,
                    ProviderCapability.GET_MACRO_SERIES,
                }
            ),
        )

    def test_world_bank_rejects_unreviewed_sources_before_transport(self) -> None:
        response = HttpResponse(
            status=200,
            headers={"Content-Type": "application/json"},
            body=json.dumps(WORLD_BANK_PAGE_1).encode(),
        )
        now = datetime(2026, 8, 21, 12, 30, tzinfo=UTC)
        for source in (1, 9999):
            with self.subTest(source=source):
                transport = RecordingTransport(response)
                adapter = WorldBankIndicatorsAdapter(
                    countries=frozenset({"US"}),
                    transport=transport,
                    clock=lambda: now,
                )
                with self.assertRaises(ProviderHttpError) as raised:
                    adapter.fetch_series(
                        country="US",
                        indicator="NY.GDP.MKTP.CD",
                        source=source,
                        per_page=1,
                        max_pages=2,
                        evaluation_timestamp=now,
                    )
                self.assertEqual(raised.exception.code, "unreviewed_world_bank_source")
                self.assertEqual(raised.exception.path, "$request.source")
                self.assertEqual(transport.requests, [])

        with self.assertRaises(ProviderHttpError) as constructor:
            WorldBankIndicatorsAdapter(
                countries=frozenset({"US"}),
                source=9999,
            )
        self.assertEqual(constructor.exception.code, "invalid_client_config")
        self.assertEqual(constructor.exception.path, "$client.source")

    def test_world_bank_request_pagination_and_payload_boundaries_fail_closed(
        self,
    ) -> None:
        now = datetime(2026, 8, 21, 12, 30, tzinfo=UTC)
        response = HttpResponse(
            status=200,
            headers={"Content-Type": "application/json"},
            body=json.dumps(WORLD_BANK_PAGE_1).encode(),
        )
        for changes in (
            {"country": "US;CN"},
            {"country": "CA"},
            {"indicator": "../GDP"},
            {"source": True},
            {"source": 0},
            {"per_page": 1001},
            {"max_pages": 11},
        ):
            with self.subTest(changes=changes):
                transport = RecordingTransport(response)
                adapter = WorldBankIndicatorsAdapter(
                    countries=frozenset({"US"}),
                    transport=transport,
                    clock=lambda: now,
                )
                arguments = {
                    "country": "US",
                    "indicator": "NY.GDP.MKTP.CD",
                    "source": 2,
                    "per_page": 1,
                    "max_pages": 2,
                    "evaluation_timestamp": now,
                }
                arguments.update(changes)
                with self.assertRaises(ProviderHttpError) as raised:
                    adapter.fetch_series(**arguments)  # type: ignore[arg-type]
                self.assertEqual(raised.exception.code, "invalid_world_bank_request")
                self.assertEqual(transport.requests, [])

        page_limit_transport = RecordingTransport(response)
        page_limit_adapter = WorldBankIndicatorsAdapter(
            countries=frozenset({"US"}),
            transport=page_limit_transport,
            clock=lambda: now,
        )
        with self.assertRaises(ProviderHttpError) as page_limit:
            page_limit_adapter.fetch_series(
                country="US",
                indicator="NY.GDP.MKTP.CD",
                source=2,
                per_page=1,
                max_pages=1,
                evaluation_timestamp=now,
            )
        self.assertEqual(page_limit.exception.code, "world_bank_page_limit")
        self.assertEqual(len(page_limit_transport.requests), 1)

        malformed_pages = []
        future = json.loads(json.dumps(WORLD_BANK_PAGE_1))
        future[0]["pages"] = 1
        future[0]["total"] = 1
        future[0]["lastupdated"] = "2026-08-22"
        malformed_pages.append(future)
        wrong_indicator = json.loads(json.dumps(WORLD_BANK_PAGE_1))
        wrong_indicator[0]["pages"] = 1
        wrong_indicator[0]["total"] = 1
        wrong_indicator[1][0]["indicator"]["id"] = "WRONG"
        malformed_pages.append(wrong_indicator)
        total_mismatch = json.loads(json.dumps(WORLD_BANK_PAGE_1))
        total_mismatch[0]["pages"] = 1
        total_mismatch[0]["total"] = 2
        malformed_pages.append(total_mismatch)

        for document in malformed_pages:
            with self.subTest(document=document):
                adapter = WorldBankIndicatorsAdapter(
                    countries=frozenset({"US"}),
                    transport=RecordingTransport(
                        HttpResponse(
                            status=200,
                            headers={"Content-Type": "application/json"},
                            body=json.dumps(document).encode(),
                        )
                    ),
                    clock=lambda: now,
                )
                with self.assertRaises(ProviderHttpError) as raised:
                    adapter.fetch_series(
                        country="US",
                        indicator="NY.GDP.MKTP.CD",
                        source=2,
                        per_page=1,
                        max_pages=1,
                        evaluation_timestamp=now,
                    )
                self.assertEqual(raised.exception.code, "invalid_world_bank_payload")

    def test_world_bank_pages_enforce_page_size_total_geometry_and_max_records(
        self,
    ) -> None:
        now = datetime(2026, 8, 21, 12, 30, tzinfo=UTC)
        overfull = json.loads(json.dumps(WORLD_BANK_PAGE_1))
        overfull[0].update({"pages": 1, "per_page": 1, "total": 2})
        second = json.loads(json.dumps(overfull[1][0]))
        second["date"] = "2023"
        overfull[1].append(second)

        adapter = WorldBankIndicatorsAdapter(
            countries=frozenset({"US"}),
            transport=RecordingTransport(
                HttpResponse(
                    status=200,
                    headers={"Content-Type": "application/json"},
                    body=json.dumps(overfull).encode(),
                )
            ),
            clock=lambda: now,
        )
        with self.assertRaises(ProviderHttpError) as overfull_error:
            adapter.fetch_series(
                country="US",
                indicator="NY.GDP.MKTP.CD",
                source=2,
                per_page=1,
                max_pages=1,
                max_records=2,
                evaluation_timestamp=now,
            )
        self.assertEqual(overfull_error.exception.code, "invalid_world_bank_payload")

        bounded = json.loads(json.dumps(WORLD_BANK_PAGE_1))
        adapter = WorldBankIndicatorsAdapter(
            countries=frozenset({"US"}),
            transport=RecordingTransport(
                HttpResponse(
                    status=200,
                    headers={"Content-Type": "application/json"},
                    body=json.dumps(bounded).encode(),
                )
            ),
            clock=lambda: now,
        )
        with self.assertRaises(ProviderHttpError) as record_limit:
            adapter.fetch_series(
                country="US",
                indicator="NY.GDP.MKTP.CD",
                source=2,
                per_page=1,
                max_pages=2,
                max_records=1,
                evaluation_timestamp=now,
            )
        self.assertEqual(record_limit.exception.code, "world_bank_record_limit")

    def test_world_bank_fixture_rejects_duplicate_observation_identity(self) -> None:
        now = datetime(2026, 8, 21, 12, 30, tzinfo=UTC)
        duplicate = json.loads(json.dumps(WORLD_BANK_PAGE_1))
        duplicate[0].update({"pages": 1, "per_page": 2, "total": 2})
        duplicate[1].append(json.loads(json.dumps(duplicate[1][0])))
        adapter = WorldBankIndicatorsAdapter(countries=frozenset({"US"}))

        with self.assertRaises(ProviderHttpError) as raised:
            adapter.parse_page_fixture(
                json.dumps(duplicate).encode(),
                country="US",
                indicator="NY.GDP.MKTP.CD",
                source=2,
                page=1,
                per_page=2,
                fetched_at=now,
                evaluation_timestamp=now,
            )
        self.assertEqual(raised.exception.code, "invalid_world_bank_payload")

    def test_world_bank_dates_iso3_and_numbers_use_strong_formats_and_bounds(
        self,
    ) -> None:
        now = datetime(2026, 8, 21, 12, 30, tzinfo=UTC)
        base = json.loads(json.dumps(WORLD_BANK_PAGE_1))
        base[0].update({"pages": 1, "total": 1})
        cases: list[tuple[str, object]] = [
            ("lastupdated", "20260820"),
            ("pages", "9" * 5000),
            ("countryiso3code", "usA"),
            ("countryiso3code", "USAA"),
            ("countryiso3code", "ＵＳＡ"),
            ("countryiso3code", ...),
            ("value", True),
            ("value", 10**309),
            ("decimal", True),
            ("decimal", 101),
        ]
        for field, value in cases:
            with self.subTest(field=field, value=repr(value)[:32]):
                document = json.loads(json.dumps(base))
                if field in {"lastupdated", "pages"}:
                    document[0][field] = value
                elif value is ...:
                    document[1][0].pop(field)
                else:
                    document[1][0][field] = value
                adapter = WorldBankIndicatorsAdapter(countries=frozenset({"US"}))
                with self.assertRaises(ProviderHttpError) as raised:
                    adapter.parse_page_fixture(
                        json.dumps(document).encode(),
                        country="US",
                        indicator="NY.GDP.MKTP.CD",
                        source=2,
                        page=1,
                        per_page=1,
                        fetched_at=now,
                        evaluation_timestamp=now,
                    )
                self.assertEqual(
                    raised.exception.code,
                    "invalid_world_bank_payload",
                )

    def test_world_bank_iso3_is_bound_to_the_allowlisted_iso2_country(self) -> None:
        now = datetime(2026, 8, 21, 12, 30, tzinfo=UTC)
        base = json.loads(json.dumps(WORLD_BANK_PAGE_1))
        base[0].update({"pages": 1, "total": 1})
        adapter = WorldBankIndicatorsAdapter(countries=frozenset({"US"}))

        for country_iso3 in ("CHN", None):
            with self.subTest(country_iso3=country_iso3):
                document = json.loads(json.dumps(base))
                document[1][0]["countryiso3code"] = country_iso3
                with self.assertRaises(ProviderHttpError) as raised:
                    adapter.parse_page_fixture(
                        json.dumps(document).encode(),
                        country="US",
                        indicator="NY.GDP.MKTP.CD",
                        source=2,
                        page=1,
                        per_page=1,
                        fetched_at=now,
                        evaluation_timestamp=now,
                    )
                self.assertEqual(raised.exception.code, "invalid_world_bank_payload")

        for countries in (frozenset({"ZZ"}), frozenset({"US", "ZZ"})):
            with self.subTest(countries=countries):
                with self.assertRaises(ProviderHttpError) as raised:
                    WorldBankIndicatorsAdapter(countries=countries)
                self.assertEqual(raised.exception.code, "invalid_client_config")

    def test_offline_world_bank_fixture_parse_and_public_exports_are_available(
        self,
    ) -> None:
        import openfundscore

        now = datetime(2026, 8, 21, 12, 30, tzinfo=UTC)
        document = json.loads(json.dumps(WORLD_BANK_PAGE_1))
        document[0]["pages"] = 1
        document[0]["total"] = 1
        adapter = WorldBankIndicatorsAdapter(countries=frozenset({"US"}))
        records = adapter.parse_page_fixture(
            json.dumps(document).encode(),
            country="US",
            indicator="NY.GDP.MKTP.CD",
            source=2,
            page=1,
            per_page=1,
            fetched_at=now,
            evaluation_timestamp=now,
        )
        self.assertEqual(len(records), 1)
        for name in (
            "FixedHostHttpClient",
            "ProviderHttpError",
            "SecEdgarSubmissionsAdapter",
            "WorldBankIndicatorsAdapter",
        ):
            self.assertIn(name, openfundscore.__all__)
            self.assertIsNotNone(getattr(openfundscore, name))
        self.assertEqual(openfundscore.OFFICIAL_PROVIDER_SCHEMA_VERSION, "0.2.0")

    def test_world_bank_unknown_rights_sabotage_is_blocked_by_authorization(
        self,
    ) -> None:
        now = datetime(2026, 8, 21, 12, 30, tzinfo=UTC)
        document = json.loads(json.dumps(WORLD_BANK_PAGE_1))
        document[0]["pages"] = 1
        document[0]["total"] = 1
        blocked_rights = {
            "mode": "unknown_blocked",
            "terms_url": "https://www.worldbank.org/en/about/legal/terms-of-use-for-datasets",
            "cache_allowed": False,
            "derived_works_allowed": False,
            "redistribution_allowed": False,
            "attribution_required": False,
            "public_display_allowed": False,
            "retention_days": 0,
            "reviewed_at": "2026-08-21T00:00:00Z",
        }
        adapter = WorldBankIndicatorsAdapter(countries=frozenset({"US"}))
        with (
            patch(
                "openfundscore.official_providers._world_bank_rights",
                return_value=blocked_rights,
            ),
            self.assertRaises(IngestionDenied) as raised,
        ):
            adapter.parse_page_fixture(
                json.dumps(document).encode(),
                country="US",
                indicator="NY.GDP.MKTP.CD",
                source=2,
                page=1,
                per_page=1,
                fetched_at=now,
                evaluation_timestamp=now,
            )
        self.assertEqual(raised.exception.code, "record_contract_mismatch")

    def test_live_world_bank_fetch_uses_its_post_response_clock_when_cutoff_is_omitted(
        self,
    ) -> None:
        now = datetime(2026, 8, 21, 12, 30, 0, 654321, tzinfo=UTC)
        document = json.loads(json.dumps(WORLD_BANK_PAGE_1))
        document[0]["pages"] = 1
        document[0]["total"] = 1
        adapter = WorldBankIndicatorsAdapter(
            countries=frozenset({"US"}),
            transport=RecordingTransport(
                HttpResponse(
                    status=200,
                    headers={"Content-Type": "application/json"},
                    body=json.dumps(document).encode(),
                )
            ),
            clock=lambda: now,
        )
        records = adapter.fetch_series(
            country="US",
            indicator="NY.GDP.MKTP.CD",
            source=2,
            per_page=1,
            max_pages=1,
        )
        self.assertEqual(
            records[0]["fetched_at"],
            "2026-08-21T12:30:00.654321Z",
        )


if __name__ == "__main__":
    unittest.main()
