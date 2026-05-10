"""Unit tests for backup_worker."""

import asyncio
import signal
from unittest.mock import MagicMock, patch

import pytest

from app.workers import backup_worker as worker_module


class TestCancelCheck:
    async def test_returns_false_by_default(self) -> None:
        result = await worker_module._cancel_check()
        assert result is False

    async def test_returns_true_after_sigterm(self) -> None:
        worker_module._shutdown_requested = True
        try:
            result = await worker_module._cancel_check()
            assert result is True
        finally:
            worker_module._shutdown_requested = False


class TestHandleSigterm:
    def test_sets_shutdown_flag(self) -> None:
        worker_module._shutdown_requested = False
        worker_module._handle_sigterm(signal.SIGTERM, None)
        assert worker_module._shutdown_requested is True
        worker_module._shutdown_requested = False


class TestBackupWorkerFn:
    @patch.object(worker_module, "set_correlation_id")
    @patch.object(worker_module, "clear_correlation_id")
    @patch.object(worker_module, "asyncio")
    @patch.object(worker_module, "signal")
    def test_sets_correlation_id_and_runs_execute(
        self,
        mock_signal: MagicMock,
        mock_asyncio: MagicMock,
        mock_clear: MagicMock,
        mock_set: MagicMock,
    ) -> None:
        worker_module._backup_worker_fn("job-123")

        mock_set.assert_called_once_with("job-123")
        mock_asyncio.run.assert_called_once()
        mock_clear.assert_called_once()
        mock_signal.signal.assert_called()

    @patch.object(worker_module, "set_correlation_id")
    @patch.object(worker_module, "clear_correlation_id")
    @patch.object(worker_module, "asyncio")
    @patch.object(worker_module, "signal")
    def test_resets_shutdown_flag_on_exit(
        self,
        _mock_signal: MagicMock,
        mock_asyncio: MagicMock,
        mock_clear: MagicMock,
        mock_set: MagicMock,
    ) -> None:
        worker_module._shutdown_requested = True
        worker_module._backup_worker_fn("job-456")

        assert worker_module._shutdown_requested is False
        mock_clear.assert_called_once()

    @patch.object(worker_module, "set_correlation_id")
    @patch.object(worker_module, "clear_correlation_id")
    @patch.object(worker_module, "asyncio")
    @patch.object(worker_module, "signal")
    def test_logs_and_reraises_on_exception(
        self,
        _mock_signal: MagicMock,
        mock_asyncio: MagicMock,
        mock_clear: MagicMock,
        mock_set: MagicMock,
    ) -> None:
        mock_asyncio.run.side_effect = RuntimeError("boom")

        with pytest.raises(RuntimeError, match="boom"):
            worker_module._backup_worker_fn("job-789")

        mock_clear.assert_called_once()


class TestExecute:
    @patch.object(worker_module, "create_engine")
    @patch.object(worker_module, "create_session_factory")
    @patch.object(worker_module, "dispose_engine")
    @patch.object(worker_module, "MongoConnection")
    @patch.object(worker_module, "MongodumpBackupEngine")
    @patch.object(worker_module, "MongoMetadataAdapter")
    @patch.object(worker_module, "ExecuteBackupUseCase")
    @patch.object(worker_module, "AppConfig")
    async def test_wires_dependencies_and_calls_use_case(
        self,
        mock_config_cls: MagicMock,
        mock_use_case_cls: MagicMock,
        _mock_meta_adapter_cls: MagicMock,
        _mock_engine_cls: MagicMock,
        _mock_mongo_conn_cls: MagicMock,
        mock_dispose: MagicMock,
        mock_session_factory: MagicMock,
        mock_create_engine: MagicMock,
    ) -> None:
        config = MagicMock()
        config.mongodb_uri = "mongodb://localhost:27017"
        config.backup_base_path = MagicMock()
        config.retention_full_weeks = 4
        config.retention_custom_weeks = 2
        config.retention_max_gb = 50
        mock_config_cls.return_value = config

        mock_engine = MagicMock()
        mock_create_engine.return_value = mock_engine

        mock_factory = MagicMock()
        mock_session_factory.return_value = mock_factory

        mock_session = MagicMock()
        mock_factory.return_value.__aenter__ = MagicMock(return_value=asyncio.Future())
        mock_factory.return_value.__aenter__.return_value.set_result(mock_session)
        mock_factory.return_value.__aexit__ = MagicMock(return_value=asyncio.Future())
        mock_factory.return_value.__aexit__.return_value.set_result(None)

        mock_use_case = MagicMock()
        mock_use_case.execute = MagicMock(return_value=asyncio.Future())
        mock_use_case.execute.return_value.set_result(MagicMock())
        mock_use_case_cls.return_value = mock_use_case

        mock_dispose.return_value = None

        await worker_module._execute("job-abc")

        mock_use_case_cls.assert_called_once()
        mock_use_case.execute.assert_called_once()
        call_args = mock_use_case.execute.call_args
        dto = call_args.args[0]
        assert dto.job_id == "job-abc"
        assert call_args.kwargs["cancel_check"] is worker_module._cancel_check
