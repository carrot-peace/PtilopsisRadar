# coding=utf-8
"""
远程存储后端（S3 兼容协议）

支持 Cloudflare R2、阿里云 OSS、腾讯云 COS、AWS S3、MinIO 等
使用 S3 兼容 API (boto3) 访问对象存储
数据流程：下载当天 SQLite → 合并新数据 → 上传回远程
"""

import pytz
import re
import shutil
import sys
import tempfile
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable, Dict, List, Optional, TypeVar

try:
    import boto3
    from botocore.config import Config as BotoConfig
    from botocore.exceptions import ClientError, ParamValidationError
    HAS_BOTO3 = True
except ImportError:
    HAS_BOTO3 = False
    boto3 = None
    BotoConfig = None
    ClientError = Exception
    ParamValidationError = Exception

from trendradar.storage.base import StorageBackend, NewsData, RSSItem, RSSData
from trendradar.storage.batch import StorageBatch
from trendradar.storage.errors import (
    RemoteConditionalWriteUnsupported,
    RemoteConflictError,
    RemoteDataError,
    RemoteDependencyError,
)
from trendradar.storage.results import BatchResult, DatabaseBatchResult
from trendradar.storage.sqlite_mixin import SQLiteStorageMixin
from trendradar.utils.time import (
    DEFAULT_TIMEZONE,
    get_configured_time,
    format_date_folder,
    format_time_filename,
)

MutationResult = TypeVar("MutationResult")


class RemoteStorageBackend(SQLiteStorageMixin, StorageBackend):
    """
    远程云存储后端（S3 兼容协议）

    特点：
    - 使用 S3 兼容 API 访问远程存储
    - 支持 Cloudflare R2、阿里云 OSS、腾讯云 COS、AWS S3、MinIO 等
    - 下载 SQLite 到临时目录进行操作
    - 支持数据合并和上传
    - 支持从远程拉取历史数据到本地
    - 运行结束后自动清理临时文件
    """

    def __init__(
        self,
        bucket_name: str,
        access_key_id: str,
        secret_access_key: str,
        endpoint_url: str,
        region: str = "",
        enable_txt: bool = False,  # 远程模式默认不生成 TXT
        enable_html: bool = True,
        temp_dir: Optional[str] = None,
        timezone: str = DEFAULT_TIMEZONE,
        single_writer: bool = False,
    ):
        """
        初始化远程存储后端

        Args:
            bucket_name: 存储桶名称
            access_key_id: 访问密钥 ID
            secret_access_key: 访问密钥
            endpoint_url: 服务端点 URL
            region: 区域（可选，部分服务商需要）
            enable_txt: 是否启用 TXT 快照（默认关闭）
            enable_html: 是否启用 HTML 报告
            temp_dir: 临时目录路径（默认使用系统临时目录）
            timezone: 时区配置
            single_writer: 显式允许不带条件头的单写者兼容模式
        """
        if not HAS_BOTO3:
            raise ImportError("远程存储后端需要安装 boto3: pip install boto3")

        self.bucket_name = bucket_name
        self.endpoint_url = endpoint_url
        self.region = region
        self.enable_txt = enable_txt
        self.enable_html = enable_html
        self.timezone = timezone
        self.single_writer = single_writer
        self.last_upload_error = ""

        # 调用方提供的目录只作为父目录；backend 只拥有并清理唯一子目录。
        temp_parent = Path(temp_dir) if temp_dir else Path(tempfile.gettempdir())
        temp_parent.mkdir(parents=True, exist_ok=True)
        self.temp_dir = Path(
            tempfile.mkdtemp(prefix="trendradar_", dir=str(temp_parent))
        )

        # 初始化 S3 客户端
        # 使用 virtual-hosted style addressing（主流）
        # 根据服务商选择签名版本：
        # - 腾讯云 COS 和 阿里云 OSS 使用 SigV2 以避免 chunked encoding 问题
        # - 其他服务商（AWS S3、Cloudflare R2、MinIO 等）默认使用 SigV4
        use_sigv2 = "myqcloud.com" in endpoint_url.lower() or "aliyuncs.com" in endpoint_url.lower()
        signature_version = 's3' if use_sigv2 else 's3v4'

        s3_config = BotoConfig(
            s3={"addressing_style": "virtual"},
            signature_version=signature_version,
        )

        client_kwargs = {
            "endpoint_url": endpoint_url,
            "aws_access_key_id": access_key_id,
            "aws_secret_access_key": secret_access_key,
            "config": s3_config,
        }
        if region:
            client_kwargs["region_name"] = region

        self.s3_client = boto3.client("s3", **client_kwargs)

        # 跟踪下载的文件（用于清理）
        self._downloaded_files: List[Path] = []
        self._db_connections: Dict[str, sqlite3.Connection] = {}
        self._remote_versions: Dict[tuple[Optional[str], str], str] = {}

        # 批量模式：延迟上传，避免频繁上传同一文件
        self._batch_mode = False
        self._batch_dirty: set = set()  # 待上传的 (date, db_type) 集合

        print(f"[远程存储] 初始化完成，存储桶: {bucket_name}，签名版本: {signature_version}")
        if self.single_writer:
            print(
                "[远程存储] 强警告: single_writer 已启用，"
                "远端写入不具备并发覆盖保护"
            )

    @property
    def backend_name(self) -> str:
        return "remote"

    @property
    def supports_txt(self) -> bool:
        return self.enable_txt

    # ========================================
    # SQLiteStorageMixin 抽象方法实现
    # ========================================

    def _get_configured_time(self) -> datetime:
        """获取配置时区的当前时间"""
        return get_configured_time(self.timezone)

    def _format_date_folder(self, date: Optional[str] = None) -> str:
        """格式化日期文件夹名 (ISO 格式: YYYY-MM-DD)"""
        return format_date_folder(date, self.timezone)

    def _format_time_filename(self) -> str:
        """格式化时间文件名 (格式: HH-MM)"""
        return format_time_filename(self.timezone)

    def _get_remote_db_key(self, date: Optional[str] = None, db_type: str = "news") -> str:
        """
        获取远程存储中 SQLite 文件的对象键

        Args:
            date: 日期字符串
            db_type: 数据库类型 ("news" 或 "rss")

        Returns:
            远程对象键，如 "news/2025-12-28.db" 或 "rss/2025-12-28.db"
        """
        date_folder = self._format_date_folder(date)
        return f"{db_type}/{date_folder}.db"

    def _get_local_db_path(self, date: Optional[str] = None, db_type: str = "news") -> Path:
        """
        获取本地临时 SQLite 文件路径

        Args:
            date: 日期字符串
            db_type: 数据库类型 ("news" 或 "rss")

        Returns:
            本地临时文件路径
        """
        date_folder = self._format_date_folder(date)
        db_dir = self.temp_dir / db_type
        db_dir.mkdir(parents=True, exist_ok=True)
        return db_dir / f"{date_folder}.db"

    @staticmethod
    def _is_not_found_error(error: ClientError) -> bool:
        error_code = str(error.response.get("Error", {}).get("Code", ""))
        return error_code in ("404", "NoSuchKey", "Not Found")

    def _head_object(self, remote_key: str) -> Optional[dict]:
        """Return object metadata, mapping only explicit not-found responses to None."""
        try:
            return self.s3_client.head_object(
                Bucket=self.bucket_name,
                Key=remote_key,
            )
        except ClientError as error:
            if self._is_not_found_error(error):
                return None
            raise RemoteDependencyError(
                f"HEAD failed for {remote_key}: {error}"
            ) from error
        except Exception as error:
            raise RemoteDependencyError(
                f"HEAD failed for {remote_key}: {error}"
            ) from error

    def _check_object_exists(self, r2_key: str) -> bool:
        """
        检查远程存储中对象是否存在

        Args:
            r2_key: 远程对象键

        Returns:
            是否存在
        """
        return self._head_object(r2_key) is not None

    @staticmethod
    def _validate_sqlite_file(path: Path) -> None:
        """Raise when a downloaded file is not a healthy SQLite database."""
        connection = None
        try:
            uri = f"{path.resolve().as_uri()}?mode=ro"
            connection = sqlite3.connect(uri, uri=True)
            row = connection.execute("PRAGMA quick_check").fetchone()
            if not row or row[0] != "ok":
                detail = row[0] if row else "no quick_check result"
                raise RemoteDataError(f"SQLite quick_check failed: {detail}")
        except RemoteDataError:
            raise
        except sqlite3.Error as error:
            raise RemoteDataError(
                f"Downloaded object is not a valid SQLite database: {error}"
            ) from error
        finally:
            if connection is not None:
                connection.close()

    def _download_object_to_path(
        self,
        remote_key: str,
        local_path: Path,
        metadata: dict,
    ) -> Optional[Path]:
        """Download through a validated side file and atomically replace target."""
        part_path = local_path.with_suffix(local_path.suffix + ".part")
        if part_path.exists():
            part_path.unlink()

        body = None
        try:
            try:
                response = self.s3_client.get_object(
                    Bucket=self.bucket_name,
                    Key=remote_key,
                )
            except ClientError as error:
                if self._is_not_found_error(error):
                    return None
                raise RemoteDependencyError(
                    f"GET failed for {remote_key}: {error}"
                ) from error
            except Exception as error:
                raise RemoteDependencyError(
                    f"GET failed for {remote_key}: {error}"
                ) from error

            expected_length = response.get(
                "ContentLength",
                metadata.get("ContentLength"),
            )
            if expected_length is None:
                raise RemoteDataError(
                    f"GET response for {remote_key} has no ContentLength"
                )
            try:
                expected_length = int(expected_length)
            except (TypeError, ValueError) as error:
                raise RemoteDataError(
                    f"Invalid ContentLength for {remote_key}: {expected_length!r}"
                ) from error

            body = response["Body"]
            bytes_written = 0
            with open(part_path, "wb") as file:
                for chunk in body.iter_chunks(chunk_size=1024 * 1024):
                    if chunk:
                        file.write(chunk)
                        bytes_written += len(chunk)

            if bytes_written != expected_length:
                raise RemoteDataError(
                    f"Length mismatch for {remote_key}: "
                    f"expected {expected_length}, got {bytes_written}"
                )

            self._validate_sqlite_file(part_path)
            part_path.replace(local_path)
            return local_path
        finally:
            close_body = getattr(body, "close", None)
            if callable(close_body):
                close_body()
            if part_path.exists():
                part_path.unlink()

    def download_database(
        self,
        *,
        date: str,
        db_type: str,
        local_path: Path,
    ) -> Optional[Path]:
        """Download one database to a validated, atomically replaced path."""
        if db_type not in {"news", "rss"}:
            raise ValueError(f"Unsupported database type: {db_type}")

        remote_key = self._get_remote_db_key(date, db_type)
        metadata = self._head_object(remote_key)
        if metadata is None:
            return None

        destination = Path(local_path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        return self._download_object_to_path(
            remote_key,
            destination,
            metadata,
        )

    def _download_sqlite(self, date: Optional[str] = None, db_type: str = "news") -> Optional[Path]:
        """
        从远程存储下载当天的 SQLite 文件到本地临时目录

        使用 get_object + iter_chunks 替代 download_file，
        以正确处理腾讯云 COS 的 chunked transfer encoding。

        Args:
            date: 日期字符串
            db_type: 数据库类型 ("news" 或 "rss")

        Returns:
            本地文件路径，如果不存在返回 None
        """
        r2_key = self._get_remote_db_key(date, db_type)
        local_path = self._get_local_db_path(date, db_type)

        # 确保目录存在
        local_path.parent.mkdir(parents=True, exist_ok=True)

        metadata = self._head_object(r2_key)
        if metadata is None:
            print(f"[远程存储] 文件不存在，将创建新数据库: {r2_key}")
            return None

        try:
            downloaded = self._download_object_to_path(
                r2_key,
                local_path,
                metadata,
            )
            if downloaded is None:
                print(f"[远程存储] 文件不存在，将创建新数据库: {r2_key}")
                return None
            version = metadata.get("ETag") or ""
            if version:
                self._remote_versions[(date, db_type)] = str(version)
            self._downloaded_files.append(downloaded)
            print(f"[远程存储] 已下载: {r2_key} -> {local_path}")
            return downloaded
        except Exception as e:
            print(f"[远程存储] 下载异常: {e}")
            raise

    def batch(self):
        return StorageBatch(self)

    def begin_batch(self):
        """开启异常安全的批量事务；禁止嵌套。"""
        if self._batch_mode:
            raise RuntimeError("Nested storage batches are not supported")
        self._begin_sqlite_batch()
        self._batch_mode = True
        self._batch_dirty.clear()
        self._batch_commands = {}

    def end_batch(self):
        """提交本地事务，并对每个数据库执行一次条件上传。"""
        commit_results = self._finish_sqlite_batch(commit=True)
        self._batch_mode = False
        committed_by_label = {
            label: committed
            for label, committed, _error in commit_results
        }
        result_items = []
        for date, db_type in sorted(
            self._batch_dirty,
            key=lambda item: (str(item[0]), item[1]),
        ):
            label = f"{db_type}:{self._format_date_folder(date)}"
            committed = committed_by_label.get(label, True)
            uploaded = False
            error = ""
            if committed:
                commands = self._batch_commands.get((date, db_type), [])
                uploaded, error = self._upload_batch_database(
                    date,
                    db_type,
                    commands,
                )
            result_items.append(
                DatabaseBatchResult(
                    database=label,
                    committed=committed,
                    uploaded=uploaded,
                    error=error,
                )
            )
        self._batch_dirty.clear()
        self._batch_commands = {}
        result = BatchResult(
            committed=all(
                item.committed and item.uploaded
                for item in result_items
            ),
            databases=tuple(result_items),
        )
        return result

    def abort_batch(self):
        """Rollback every opened SQLite transaction and perform zero uploads."""
        rollback_results = self._finish_sqlite_batch(commit=False)
        self._batch_mode = False
        self._batch_dirty.clear()
        self._batch_commands = {}
        return BatchResult(
            committed=False,
            databases=tuple(
                DatabaseBatchResult(
                    database=label,
                    committed=False,
                    error=error,
                )
                for label, _committed, error in rollback_results
            ),
            rolled_back=True,
        )

    def _upload_batch_database(
        self,
        date: Optional[str],
        db_type: str,
        commands,
    ) -> tuple[bool, str]:
        for attempt in range(1, 4):
            try:
                self._upload_sqlite_once(date, db_type)
                return True, ""
            except RemoteConflictError as error:
                self.last_upload_error = f"conflict: {error}"
                if attempt == 3:
                    return False, self.last_upload_error
                try:
                    self._refresh_database(date, db_type)
                    for operation, should_upload in commands:
                        replay_result = operation()
                        if not should_upload(replay_result):
                            continue
                except Exception as replay_error:
                    self.last_upload_error = str(replay_error)
                    return False, self.last_upload_error
            except Exception as error:
                self.last_upload_error = str(error)
                return False, self.last_upload_error
        return False, self.last_upload_error

    @staticmethod
    def _is_conflict_error(error: ClientError) -> bool:
        error_code = str(error.response.get("Error", {}).get("Code", ""))
        return error_code in (
            "409",
            "412",
            "ConditionalRequestConflict",
            "PreconditionFailed",
        )

    @staticmethod
    def _is_unsupported_condition_error(error: ClientError) -> bool:
        error_code = str(error.response.get("Error", {}).get("Code", ""))
        return error_code in (
            "InvalidArgument",
            "InvalidRequest",
            "NotImplemented",
            "Unsupported",
            "UnsupportedOperation",
        )

    def _upload_sqlite_once(
        self,
        date: Optional[str] = None,
        db_type: str = "news",
    ) -> str:
        """Perform one conditional PUT and return the new remote version."""
        local_path = self._get_local_db_path(date, db_type)
        remote_key = self._get_remote_db_key(date, db_type)
        if not local_path.exists():
            raise RemoteDataError(f"Local database does not exist: {local_path}")

        local_size = local_path.stat().st_size
        file_content = local_path.read_bytes()
        print(
            f"[远程存储] 准备上传: {local_path} "
            f"({local_size} bytes) -> {remote_key}"
        )

        request = {
            "Bucket": self.bucket_name,
            "Key": remote_key,
            "Body": file_content,
            "ContentLength": local_size,
            "ContentType": "application/x-sqlite3",
        }
        version_key = (date, db_type)
        if not self.single_writer:
            current_version = self._remote_versions.get(version_key)
            if current_version:
                request["IfMatch"] = current_version
            else:
                request["IfNoneMatch"] = "*"

        try:
            response = self.s3_client.put_object(**request)
        except ParamValidationError as error:
            if not self.single_writer:
                raise RemoteConditionalWriteUnsupported(
                    f"Provider SDK does not support conditional PUT: {error}"
                ) from error
            raise RemoteDependencyError(
                f"PUT failed for {remote_key}: {error}"
            ) from error
        except ClientError as error:
            if self._is_conflict_error(error):
                raise RemoteConflictError(
                    f"Conditional PUT conflict for {remote_key}: {error}"
                ) from error
            if (
                not self.single_writer
                and self._is_unsupported_condition_error(error)
            ):
                raise RemoteConditionalWriteUnsupported(
                    f"Provider rejected conditional PUT for {remote_key}: {error}"
                ) from error
            raise RemoteDependencyError(
                f"PUT failed for {remote_key}: {error}"
            ) from error
        except Exception as error:
            raise RemoteDependencyError(
                f"PUT failed for {remote_key}: {error}"
            ) from error

        new_version = response.get("ETag") if response else None
        if not new_version and self.single_writer:
            metadata = self._head_object(remote_key)
            new_version = metadata.get("ETag") if metadata else None
        if not new_version:
            raise RemoteDependencyError(
                f"PUT for {remote_key} returned no remote version"
            )

        self._remote_versions[version_key] = str(new_version)
        self.last_upload_error = ""
        print(f"[远程存储] 已上传: {local_path} -> {remote_key}")
        return str(new_version)

    def _upload_sqlite(
        self,
        date: Optional[str] = None,
        db_type: str = "news",
    ) -> bool:
        """Compatibility upload façade used by legacy batch handling."""
        if self._batch_mode:
            self._batch_dirty.add((date, db_type))
            return True
        try:
            self._upload_sqlite_once(date, db_type)
            return True
        except Exception as error:
            self.last_upload_error = str(error)
            print(f"[远程存储] 上传失败: {error}")
            return False

    def _refresh_database(
        self,
        date: Optional[str],
        db_type: str,
    ) -> None:
        """Discard the stale local copy and download the current remote version."""
        local_path = self._get_local_db_path(date, db_type)
        db_path = str(local_path)
        connection = self._db_connections.pop(db_path, None)
        if connection is not None:
            connection.close()
        if local_path.exists():
            local_path.unlink()
        self._remote_versions.pop((date, db_type), None)
        self._download_sqlite(date, db_type)

    def _execute_remote_mutation(
        self,
        date: Optional[str],
        db_type: str,
        operation: Callable[[], MutationResult],
        should_upload: Callable[[MutationResult], bool],
    ) -> tuple[MutationResult, bool]:
        """Apply, conditionally upload, and replay a deterministic mutation."""
        reported_result = operation()
        replay_result = reported_result
        if not should_upload(replay_result):
            return reported_result, False

        if self._batch_mode:
            self._batch_dirty.add((date, db_type))
            commands = getattr(self, "_batch_commands", None)
            if commands is None:
                commands = {}
                self._batch_commands = commands
            commands.setdefault((date, db_type), []).append(
                (operation, should_upload)
            )
            return reported_result, True

        for attempt in range(1, 4):
            try:
                self._upload_sqlite_once(date, db_type)
                return reported_result, True
            except RemoteConflictError as error:
                self.last_upload_error = f"conflict: {error}"
                if attempt == 3:
                    print(
                        f"[远程存储] CAS 冲突重试耗尽 "
                        f"({attempt}/3): {error}"
                    )
                    return reported_result, False
                print(
                    f"[远程存储] CAS 冲突，刷新后重放 "
                    f"({attempt}/3): {error}"
                )
                try:
                    self._refresh_database(date, db_type)
                    replay_result = operation()
                except Exception as refresh_error:
                    self.last_upload_error = str(refresh_error)
                    print(f"[远程存储] CAS 重放失败: {refresh_error}")
                    return reported_result, False
                if not should_upload(replay_result):
                    return reported_result, True
            except (
                RemoteConditionalWriteUnsupported,
                RemoteDependencyError,
                RemoteDataError,
            ) as error:
                self.last_upload_error = str(error)
                print(f"[远程存储] 上传失败: {error}")
                return reported_result, False

        return reported_result, False

    def _get_connection(self, date: Optional[str] = None, db_type: str = "news") -> sqlite3.Connection:
        """
        获取数据库连接

        Args:
            date: 日期字符串
            db_type: 数据库类型 ("news" 或 "rss")

        Returns:
            数据库连接
        """
        local_path = self._get_local_db_path(date, db_type)
        db_path = str(local_path)

        if db_path not in self._db_connections:
            # 确保目录存在
            local_path.parent.mkdir(parents=True, exist_ok=True)

            # 如果本地不存在，尝试从远程存储下载
            if not local_path.exists():
                self._download_sqlite(date, db_type)

            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA foreign_keys = ON")
            conn.execute("PRAGMA busy_timeout = 5000")
            self._init_tables(conn, db_type)
            self._db_connections[db_path] = conn

        connection = self._db_connections[db_path]
        labels = getattr(self, "_sqlite_connection_labels", None)
        if labels is None:
            labels = {}
            self._sqlite_connection_labels = labels
        labels[id(connection)] = f"{db_type}:{self._format_date_folder(date)}"
        return connection

    # ========================================
    # StorageBackend 接口实现（委托给 mixin + 上传）
    # ========================================

    def save_news_data(self, data: NewsData) -> bool:
        """
        保存新闻数据到远程存储

        流程：下载现有数据库 → 插入/更新数据 → 上传回远程存储
        """
        # 查询已有记录数
        conn = self._get_connection(data.date)
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) as count FROM news_items")
        row = cursor.fetchone()
        existing_count = row[0] if row else 0
        if existing_count > 0:
            print(f"[远程存储] 已有 {existing_count} 条历史记录，将合并新数据")

        result, synced = self._execute_remote_mutation(
            data.date,
            "news",
            lambda: self._save_news_data_impl(data, "[远程存储]"),
            lambda outcome: outcome.committed,
        )
        if not result.committed or not synced:
            return False

        # 查询合并后的总记录数
        conn = self._get_connection(data.date)
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) as count FROM news_items")
        row = cursor.fetchone()
        final_count = row[0] if row else 0

        # 输出详细的存储统计日志
        log_parts = [f"[远程存储] 处理完成：新增 {result.inserted} 条"]
        if result.updated > 0:
            log_parts.append(f"更新 {result.updated} 条")
        if result.title_changed > 0:
            log_parts.append(f"标题变更 {result.title_changed} 条")
        if result.off_list > 0:
            log_parts.append(f"脱榜 {result.off_list} 条")
        log_parts.append(f"(去重后总计: {final_count} 条)")
        print("，".join(log_parts))

        print(f"[远程存储] 数据已同步到远程存储")
        return True

    def get_today_all_data(self, date: Optional[str] = None) -> Optional[NewsData]:
        """获取指定日期的所有新闻数据（合并后）"""
        return self._get_today_all_data_impl(date)

    def get_latest_crawl_data(self, date: Optional[str] = None) -> Optional[NewsData]:
        """获取最新一次抓取的数据"""
        return self._get_latest_crawl_data_impl(date)

    def detect_new_titles(self, current_data: NewsData) -> Dict[str, Dict]:
        """检测新增的标题"""
        return self._detect_new_titles_impl(current_data)

    def is_first_crawl_today(self, date: Optional[str] = None) -> bool:
        """检查是否是当天第一次抓取"""
        return self._is_first_crawl_today_impl(date)

    # ========================================
    # 时间段执行记录（调度系统）
    # ========================================

    def has_period_executed(self, date_str: str, period_key: str, action: str) -> bool:
        """检查指定时间段的某个 action 是否已执行"""
        return self._has_period_executed_impl(date_str, period_key, action)

    def record_period_execution(self, date_str: str, period_key: str, action: str) -> bool:
        """记录时间段的 action 执行"""
        success, synced = self._execute_remote_mutation(
            date_str,
            "news",
            lambda: self._record_period_execution_impl(
                date_str,
                period_key,
                action,
            ),
            bool,
        )

        if success and synced:
            now_str = self._get_configured_time().strftime("%Y-%m-%d %H:%M:%S")
            print(f"[远程存储] 时间段执行记录已保存: {period_key}/{action} at {now_str}")
            print(f"[远程存储] 时间段执行记录已同步到远程存储")
            return True

        return False

    # ========================================
    # RSS 数据存储方法
    # ========================================

    def save_rss_data(self, data: RSSData) -> bool:
        """
        保存 RSS 数据到远程存储

        流程：下载现有数据库 → 插入/更新数据 → 上传回远程存储
        """
        result, synced = self._execute_remote_mutation(
            data.date,
            "rss",
            lambda: self._save_rss_data_impl(data, "[远程存储]"),
            lambda outcome: outcome.committed,
        )
        if not result.committed or not synced:
            return False

        # 输出统计日志
        log_parts = [f"[远程存储] RSS 处理完成：新增 {result.inserted} 条"]
        if result.updated > 0:
            log_parts.append(f"更新 {result.updated} 条")
        print("，".join(log_parts))

        print(f"[远程存储] RSS 数据已同步到远程存储")
        return True

    def get_rss_data(self, date: Optional[str] = None) -> Optional[RSSData]:
        """获取指定日期的所有 RSS 数据"""
        return self._get_rss_data_impl(date)

    def detect_new_rss_items(self, current_data: RSSData) -> Dict[str, List[RSSItem]]:
        """检测新增的 RSS 条目"""
        return self._detect_new_rss_items_impl(current_data)

    def get_latest_rss_data(self, date: Optional[str] = None) -> Optional[RSSData]:
        """获取最新一次抓取的 RSS 数据"""
        return self._get_latest_rss_data_impl(date)

    # ========================================
    # AI 智能筛选存储方法
    # ========================================

    def get_active_ai_filter_tags(self, date=None, interests_file="ai_interests.txt"):
        return self._get_active_tags_impl(date, interests_file)

    def get_latest_prompt_hash(self, date=None, interests_file="ai_interests.txt"):
        return self._get_latest_prompt_hash_impl(date, interests_file)

    def get_latest_ai_filter_tag_version(self, date=None):
        return self._get_latest_tag_version_impl(date)

    def _execute_count_mutation(self, date, operation):
        count, synced = self._execute_remote_mutation(
            date,
            "news",
            operation,
            lambda value: value > 0,
        )
        return count if synced else 0

    def deprecate_all_ai_filter_tags(self, date=None, interests_file="ai_interests.txt"):
        return self._execute_count_mutation(
            date,
            lambda: self._deprecate_all_tags_impl(date, interests_file),
        )

    def save_ai_filter_tags(self, tags, version, prompt_hash, date=None, interests_file="ai_interests.txt"):
        return self._execute_count_mutation(
            date,
            lambda: self._save_tags_impl(
                date,
                tags,
                version,
                prompt_hash,
                interests_file,
            ),
        )

    def save_ai_filter_results(self, results, date=None):
        return self._execute_count_mutation(
            date,
            lambda: self._save_filter_results_impl(date, results),
        )

    def get_active_ai_filter_results(self, date=None, interests_file="ai_interests.txt"):
        return self._get_active_filter_results_impl(date, interests_file)

    def deprecate_specific_ai_filter_tags(self, tag_ids, date=None):
        return self._execute_count_mutation(
            date,
            lambda: self._deprecate_specific_tags_impl(date, tag_ids),
        )

    def update_ai_filter_tags_hash(self, interests_file, new_hash, date=None):
        return self._execute_count_mutation(
            date,
            lambda: self._update_tags_hash_impl(
                date,
                interests_file,
                new_hash,
            ),
        )

    def update_ai_filter_tag_descriptions(self, tag_updates, date=None, interests_file="ai_interests.txt"):
        return self._execute_count_mutation(
            date,
            lambda: self._update_tag_descriptions_impl(
                date,
                tag_updates,
                interests_file,
            ),
        )

    def update_ai_filter_tag_priorities(self, tag_priorities, date=None, interests_file="ai_interests.txt"):
        return self._execute_count_mutation(
            date,
            lambda: self._update_tag_priorities_impl(
                date,
                tag_priorities,
                interests_file,
            ),
        )

    def save_analyzed_news(self, news_ids, source_type, interests_file, prompt_hash, matched_ids, date=None):
        return self._execute_count_mutation(
            date,
            lambda: self._save_analyzed_news_impl(
                date,
                news_ids,
                source_type,
                interests_file,
                prompt_hash,
                matched_ids,
            ),
        )

    def get_analyzed_news_ids(self, source_type="hotlist", date=None, interests_file="ai_interests.txt"):
        return self._get_analyzed_news_ids_impl(date, source_type, interests_file)

    def clear_analyzed_news(self, date=None, interests_file="ai_interests.txt"):
        return self._execute_count_mutation(
            date,
            lambda: self._clear_analyzed_news_impl(date, interests_file),
        )

    def clear_unmatched_analyzed_news(self, date=None, interests_file="ai_interests.txt"):
        return self._execute_count_mutation(
            date,
            lambda: self._clear_unmatched_analyzed_news_impl(
                date,
                interests_file,
            ),
        )

    def get_all_news_ids(self, date=None):
        return self._get_all_news_ids_impl(date)

    def get_all_rss_ids(self, date=None):
        return self._get_all_rss_ids_impl(date)

    # ========================================
    # 远程特有功能：TXT/HTML 快照（临时目录）
    # ========================================

    def save_txt_snapshot(self, data: NewsData) -> Optional[str]:
        """保存 TXT 快照（远程存储模式下默认不支持）"""
        if not self.enable_txt:
            return None

        # 如果启用，保存到本地临时目录
        try:
            date_folder = self._format_date_folder(data.date)
            txt_dir = self.temp_dir / date_folder / "txt"
            txt_dir.mkdir(parents=True, exist_ok=True)

            file_path = txt_dir / f"{data.crawl_time}.txt"

            with open(file_path, "w", encoding="utf-8") as f:
                for source_id, news_list in data.items.items():
                    source_name = data.id_to_name.get(source_id, source_id)

                    if source_name and source_name != source_id:
                        f.write(f"{source_id} | {source_name}\n")
                    else:
                        f.write(f"{source_id}\n")

                    sorted_news = sorted(news_list, key=lambda x: x.rank)

                    for item in sorted_news:
                        line = f"{item.rank}. {item.title}"
                        if item.url:
                            line += f" [URL:{item.url}]"
                        if item.mobile_url:
                            line += f" [MOBILE:{item.mobile_url}]"
                        f.write(line + "\n")

                    f.write("\n")

                if data.failed_ids:
                    f.write("==== 以下ID请求失败 ====\n")
                    for failed_id in data.failed_ids:
                        f.write(f"{failed_id}\n")

            print(f"[远程存储] TXT 快照已保存: {file_path}")
            return str(file_path)

        except Exception as e:
            print(f"[远程存储] 保存 TXT 快照失败: {e}")
            return None

    def save_html_report(self, html_content: str, filename: str) -> Optional[str]:
        """保存 HTML 报告到临时目录"""
        if not self.enable_html:
            return None

        try:
            date_folder = self._format_date_folder()
            html_dir = self.temp_dir / date_folder / "html"
            html_dir.mkdir(parents=True, exist_ok=True)

            file_path = html_dir / filename

            with open(file_path, "w", encoding="utf-8") as f:
                f.write(html_content)

            print(f"[远程存储] HTML 报告已保存: {file_path}")
            return str(file_path)

        except Exception as e:
            print(f"[远程存储] 保存 HTML 报告失败: {e}")
            return None

    # ========================================
    # 远程特有功能：资源清理
    # ========================================

    def cleanup(self) -> None:
        """清理资源（关闭连接和删除临时文件）"""
        # 检查 Python 是否正在关闭
        if sys.meta_path is None:
            return

        # 关闭数据库连接
        db_connections = getattr(self, "_db_connections", {})
        for db_path, conn in list(db_connections.items()):
            try:
                conn.close()
                print(f"[远程存储] 关闭数据库连接: {db_path}")
            except Exception as e:
                print(f"[远程存储] 关闭连接失败 {db_path}: {e}")

        if db_connections:
            db_connections.clear()

        # 删除临时目录
        temp_dir = getattr(self, "temp_dir", None)
        if temp_dir:
            try:
                if temp_dir.exists():
                    shutil.rmtree(temp_dir)
                    print(f"[远程存储] 临时目录已清理: {temp_dir}")
            except Exception as e:
                # 忽略 Python 关闭时的错误
                if sys.meta_path is not None:
                    print(f"[远程存储] 清理临时目录失败: {e}")

        downloaded_files = getattr(self, "_downloaded_files", None)
        if downloaded_files:
            downloaded_files.clear()

    def cleanup_old_data(self, retention_days: int) -> int:
        """
        清理远程存储上的过期数据

        Args:
            retention_days: 保留天数（0 表示不清理）

        Returns:
            删除的数据库文件数量
        """
        if retention_days <= 0:
            return 0

        deleted_count = 0
        cutoff_date = self._get_configured_time() - timedelta(days=retention_days)

        try:
            # 列出远程存储中 news/ 前缀下的所有对象
            paginator = self.s3_client.get_paginator('list_objects_v2')
            pages = paginator.paginate(Bucket=self.bucket_name, Prefix="news/")

            # 收集需要删除的对象键
            objects_to_delete = []
            deleted_dates = set()

            for page in pages:
                if 'Contents' not in page:
                    continue

                for obj in page['Contents']:
                    key = obj['Key']

                    # 解析日期（格式: news/YYYY-MM-DD.db）
                    folder_date = None
                    date_str = None
                    try:
                        date_match = re.match(r'news/(\d{4})-(\d{2})-(\d{2})\.db$', key)
                        if date_match:
                            folder_date = datetime(
                                int(date_match.group(1)),
                                int(date_match.group(2)),
                                int(date_match.group(3)),
                                tzinfo=pytz.timezone(self.timezone)
                            )
                            date_str = f"{date_match.group(1)}-{date_match.group(2)}-{date_match.group(3)}"
                    except Exception:
                        continue

                    if folder_date and folder_date < cutoff_date:
                        objects_to_delete.append({'Key': key})
                        deleted_dates.add(date_str)

            # 批量删除对象（每次最多 1000 个）
            if objects_to_delete:
                batch_size = 1000
                for i in range(0, len(objects_to_delete), batch_size):
                    batch = objects_to_delete[i:i + batch_size]
                    try:
                        self.s3_client.delete_objects(
                            Bucket=self.bucket_name,
                            Delete={'Objects': batch}
                        )
                        print(f"[远程存储] 删除 {len(batch)} 个对象")
                    except Exception as e:
                        print(f"[远程存储] 批量删除失败: {e}")

                deleted_count = len(deleted_dates)
                for date_str in sorted(deleted_dates):
                    print(f"[远程存储] 清理过期数据: news/{date_str}.db")

                print(f"[远程存储] 共清理 {deleted_count} 个过期日期数据库文件")

            return deleted_count

        except Exception as e:
            print(f"[远程存储] 清理过期数据失败: {e}")
            return deleted_count

    def __del__(self):
        """析构函数"""
        # 检查 Python 是否正在关闭
        if sys.meta_path is None:
            return
        try:
            self.cleanup()
        except Exception:
            # Python 关闭时可能会出错，忽略即可
            pass

    # ========================================
    # 远程特有功能：数据拉取和列表
    # ========================================

    def pull_recent_days(self, days: int, local_data_dir: str = "output") -> int:
        """
        从远程拉取最近 N 天的数据到本地

        Args:
            days: 拉取天数
            local_data_dir: 本地数据目录

        Returns:
            成功拉取的数据库文件数量
        """
        if days <= 0:
            return 0

        local_dir = Path(local_data_dir)
        local_dir.mkdir(parents=True, exist_ok=True)

        pulled_count = 0
        now = self._get_configured_time()

        print(f"[远程存储] 开始拉取最近 {days} 天的数据...")

        for i in range(days):
            date = now - timedelta(days=i)
            date_str = date.strftime("%Y-%m-%d")

            # 本地目标路径
            local_db_path = local_dir / "news" / f"{date_str}.db"

            # 如果本地已存在，跳过
            if local_db_path.exists():
                print(f"[远程存储] 跳过（本地已存在）: {date_str}")
                continue

            # 远程对象键
            remote_key = f"news/{date_str}.db"

            try:
                downloaded = self.download_database(
                    date=date_str,
                    db_type="news",
                    local_path=local_db_path,
                )
                if downloaded is None:
                    print(f"[远程存储] 跳过（远程不存在）: {date_str}")
                    continue
                print(f"[远程存储] 已拉取: {remote_key} -> {local_db_path}")
                pulled_count += 1
            except Exception as e:
                print(f"[远程存储] 拉取失败 ({date_str}): {e}")

        print(f"[远程存储] 拉取完成，共下载 {pulled_count} 个数据库文件")
        return pulled_count

    def list_remote_dates(self) -> List[str]:
        """
        列出远程存储中所有可用的日期

        Returns:
            日期字符串列表（YYYY-MM-DD 格式）
        """
        dates = []

        try:
            paginator = self.s3_client.get_paginator('list_objects_v2')
            pages = paginator.paginate(Bucket=self.bucket_name, Prefix="news/")

            for page in pages:
                if 'Contents' not in page:
                    continue

                for obj in page['Contents']:
                    key = obj['Key']
                    # 解析日期
                    date_match = re.match(r'news/(\d{4}-\d{2}-\d{2})\.db$', key)
                    if date_match:
                        dates.append(date_match.group(1))

            return sorted(dates, reverse=True)

        except Exception as e:
            print(f"[远程存储] 列出远程日期失败: {e}")
            return []
