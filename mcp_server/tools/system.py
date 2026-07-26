"""
系统管理工具

实现系统状态查询和版本检查功能。
"""

from pathlib import Path
from typing import Dict, Optional

from ..services.data_service import DataService
from ..utils.errors import MCPError
from trendradar.versioning import parse_version_tuple


class SystemManagementTools:
    """系统管理工具类"""

    def __init__(self, project_root: str = None):
        """
        初始化系统管理工具

        Args:
            project_root: 项目根目录
        """
        self.data_service = DataService(project_root)
        if project_root:
            self.project_root = Path(project_root)
        else:
            # 获取项目根目录
            current_file = Path(__file__)
            self.project_root = current_file.parent.parent.parent

    def get_system_status(self) -> Dict:
        """
        获取系统运行状态和健康检查信息

        Returns:
            系统状态字典

        Example:
            >>> tools = SystemManagementTools()
            >>> result = tools.get_system_status()
            >>> print(result['system']['version'])
        """
        try:
            # 获取系统状态
            status = self.data_service.get_system_status()

            return {
                "success": True,
                "summary": {
                    "description": "系统运行状态和健康检查信息"
                },
                "data": status
            }

        except MCPError as e:
            return {
                "success": False,
                "error": e.to_dict()
            }
        except Exception as e:
            return {
                "success": False,
                "error": {
                    "code": "INTERNAL_ERROR",
                    "message": str(e)
                }
            }

    def check_version(self, proxy_url: Optional[str] = None) -> Dict:
        """
        检查版本更新

        同时检查 Ptilopsis Radar 和 MCP Server 两个组件的版本更新。
        远程版本 URL 从 config.yaml 获取：
        - version_check_url: Ptilopsis Radar 版本
        - mcp_version_check_url: MCP Server 版本

        Args:
            proxy_url: 可选的代理URL，用于访问远程版本

        Returns:
            版本检查结果字典，包含：
            - success: 是否成功
            - trendradar: Ptilopsis Radar 版本检查结果
            - mcp: MCP Server 版本检查结果
            - any_update: 是否有任何组件需要更新

        Example:
            >>> tools = SystemManagementTools()
            >>> result = tools.check_version()
            >>> print(result['data']['any_update'])
        """
        import yaml
        import requests

        def parse_version(version_str: str):
            """将版本号字符串解析为元组，支持 x.y.z-suffix 展示版本"""
            return parse_version_tuple(version_str)

        def check_single_version(
            name: str,
            local_version: str,
            remote_url: str,
            proxies: Optional[Dict],
            headers: Dict
        ) -> Dict:
            """检查单个组件的版本（支持 CDN 多源回退）"""
            try:
                from trendradar.core.cdn import fetch_with_fallback
                proxy_url = None
                if proxies:
                    proxy_url = proxies.get("https") or proxies.get("http")
                remote_version = fetch_with_fallback(remote_url, proxy_url)

                if not remote_version:
                    return {
                        "success": False,
                        "name": name,
                        "current_version": local_version,
                        "error": "所有版本检查源均不可用"
                    }

                local_tuple = parse_version(local_version)
                remote_tuple = parse_version(remote_version)
                need_update = local_tuple < remote_tuple

                if need_update:
                    message = f"发现新版本 {remote_version}，当前版本 {local_version}，建议更新"
                elif local_tuple > remote_tuple:
                    message = f"当前版本 {local_version} 高于远程版本 {remote_version}（可能是开发版本）"
                else:
                    message = f"当前版本 {local_version} 已是最新版本"

                return {
                    "success": True,
                    "name": name,
                    "current_version": local_version,
                    "remote_version": remote_version,
                    "need_update": need_update,
                    "current_parsed": list(local_tuple),
                    "remote_parsed": list(remote_tuple),
                    "message": message
                }
            except Exception as e:
                return {
                    "success": False,
                    "name": name,
                    "current_version": local_version,
                    "error": str(e)
                }

        try:
            # 导入本地版本
            from trendradar import __version__ as trendradar_version
            from mcp_server import __version__ as mcp_version

            # 从配置文件获取远程版本 URL
            config_path = self.project_root / "config" / "config.yaml"
            if not config_path.exists():
                return {
                    "success": False,
                    "error": {
                        "code": "CONFIG_NOT_FOUND",
                        "message": f"配置文件不存在: {config_path}"
                    }
                }

            with open(config_path, "r", encoding="utf-8") as f:
                config_data = yaml.safe_load(f)

            advanced_config = config_data.get("advanced", {})
            trendradar_url = advanced_config.get(
                "version_check_url",
                "https://raw.githubusercontent.com/carrot-peace/PtilopsisRadar/refs/heads/master/version"
            )
            mcp_url = advanced_config.get(
                "mcp_version_check_url",
                "https://raw.githubusercontent.com/carrot-peace/PtilopsisRadar/refs/heads/master/version_mcp"
            )

            # 配置代理
            proxies = None
            if proxy_url:
                proxies = {"http": proxy_url, "https": proxy_url}

            # 请求头
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Accept": "text/plain, */*",
                "Cache-Control": "no-cache",
            }

            # 检查两个版本
            trendradar_result = check_single_version(
                "Ptilopsis Radar", trendradar_version, trendradar_url, proxies, headers
            )
            mcp_result = check_single_version(
                "MCP Server", mcp_version, mcp_url, proxies, headers
            )

            # 判断是否有任何更新
            any_update = (
                (trendradar_result.get("success") and trendradar_result.get("need_update", False)) or
                (mcp_result.get("success") and mcp_result.get("need_update", False))
            )

            return {
                "success": True,
                "summary": {
                    "description": "版本检查结果（Ptilopsis Radar + MCP Server）",
                    "any_update": any_update
                },
                "data": {
                    "trendradar": trendradar_result,
                    "mcp": mcp_result,
                    "any_update": any_update
                }
            }

        except ImportError as e:
            return {
                "success": False,
                "error": {
                    "code": "IMPORT_ERROR",
                    "message": f"无法导入版本信息: {str(e)}"
                }
            }
        except Exception as e:
            return {
                "success": False,
                "error": {
                    "code": "INTERNAL_ERROR",
                    "message": str(e)
                }
            }
