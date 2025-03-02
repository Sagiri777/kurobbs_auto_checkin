import os
import sys
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional, Tuple, Type
from enum import Enum
import time

import requests
from loguru import logger
from pydantic import BaseModel, Field, ValidationError

from ext_bark import send_bark_notification
from ext_wechatWorkApp import send_wechat_work_notification

# Constants
DEFAULT_TIMEOUT = 10
MAX_RETRIES = 3
RETRY_DELAY = 1

class NotificationMode(str, Enum):
    WECHAT_WORK = "wechatWorkApp"
    BARK = "bark"
    CONSOLE = "console"

class ResponseStatus(str, Enum):
    SUCCESS = "success"
    FAILURE = "failure"

class GameInfo(BaseModel):
    gameId: int
    serverId: int
    roleId: int
    userId: int

class ApiResponse(BaseModel):
    code: int = Field(..., description="状态码")
    msg: str = Field(..., description="提示信息")
    success: Optional[bool] = Field(None, description="操作是否成功")
    data: Optional[Any] = Field(None, description="响应数据")

class KurobbsClientException(Exception):
    """库街区客户端异常基类"""
    pass

class RequestException(KurobbsClientException):
    """网络请求异常"""
    pass

class ValidationException(KurobbsClientException):
    """数据验证异常"""
    pass

class KurobbsClient:
    API_ENDPOINTS = {
        "find_role_list": "https://api.kurobbs.com/user/role/findRoleList",
        "sign_in": "https://api.kurobbs.com/encourage/signIn/v2",
        "user_sign": "https://api.kurobbs.com/user/signIn",
        "init_sign_check": "https://api.kurobbs.com/encourage/signIn/initSignInV2"
    }

    DEFAULT_HEADERS = {
        'User-Agent': "Mozilla/5.0 (iPhone; CPU iPhone OS 16_2 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko)  KuroGameBox/2.4.0",
        'Accept': "application/json, text/plain, */*",
        'devcode': "221.220.134.224, Mozilla/5.0 (iPhone; CPU iPhone OS 16_2 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko)  KuroGameBox/2.4.0",
        'source': "ios",
        'accept-language': "zh-CN,zh-Hans;q=0.9",
        'origin': "https://web-static.kurobbs.com"
    }

    def __init__(self, token: str):
        if not token:
            raise ValueError("Token不能为空")
        self.token = token
        self.results: Dict[str, str] = {}
        self.exceptions: List[Exception] = []

    @property
    def headers(self) -> Dict[str, str]:
        """动态生成包含token的请求头"""
        return {**self.DEFAULT_HEADERS, 'token': self.token}

    def _request_with_retry(
        self,
        method: Callable,
        url: str,
        **kwargs
    ) -> requests.Response:
        """带重试机制的请求处理"""
        for attempt in range(MAX_RETRIES):
            try:
                response = method(url, timeout=DEFAULT_TIMEOUT, **kwargs)
                response.raise_for_status()
                return response
            except requests.exceptions.RequestException as e:
                if attempt < MAX_RETRIES - 1:
                    logger.warning(f"请求失败，正在重试 ({attempt+1}/{MAX_RETRIES}): {str(e)}")
                    time.sleep(RETRY_DELAY * (attempt + 1))
                else:
                    raise RequestException(f"请求失败: {str(e)}") from e

    def check_sign_status(self, game_info: GameInfo) -> bool:
        """检查当前签到状态"""
        try:
            form_data = {
                "gameId": game_info.gameId,
                "serverId": game_info.serverId,
                "roleId": game_info.roleId,
                "userId": game_info.userId
            }
            
            response = self.make_request(
                endpoint="init_sign_check",
                data=form_data,
                use_json=False  # 使用form-urlencoded编码
            )
            
            # 验证响应数据结构
            if not isinstance(response.data, dict):
                raise ValidationException("无效的响应数据结构")
            
            return response.data.get("isSigIn", False)
        
        except Exception as e:
            self.exceptions.append(e)
            logger.warning(f"签到状态检查失败: {str(e)}")
            return False  # 默认视为未签到

    def make_request(self, endpoint: str, data: Dict[str, Any], use_json: bool = True) -> ApiResponse:
        """增强的请求处理方法"""
        try:
            url = self.API_ENDPOINTS[endpoint]
            logger.debug(f"请求API: {url}，参数: {data}")
            
            # 动态设置Content-Type
            headers = self.headers.copy()
            headers['Content-Type'] = 'application/json' if use_json else 'application/x-www-form-urlencoded'
            
            response = self._request_with_retry(
                requests.post,
                url,
                headers=headers,
                json=data if use_json else None,
                data=data if not use_json else None
            )
            
            # 数据验证
            try:
                validated = ApiResponse.model_validate_json(response.text)
                logger.debug(f"API响应: {validated.model_dump_json(indent=2, exclude={'data'})}")
                return validated
            except ValidationError as e:
                raise ValidationException(f"响应验证失败: {str(e)}") from e
                
        except Exception as e:
            self.exceptions.append(e)
            raise

    def get_user_game_list(self, game_id: int) -> List[GameInfo]:
        """获取用户游戏角色列表"""
        try:
            response = self.make_request("find_role_list", {"gameId": game_id})
            if not response.data:
                return []
            return [GameInfo(**item) for item in response.data]
        except Exception as e:
            self.exceptions.append(e)
            raise

    def _build_checkin_data(self, game_id: int = 3) -> Dict[str, Any]:
        """构建签到请求参数"""
        try:
            game_list = self.get_user_game_list(game_id)
            if not game_list:
                raise KurobbsClientException("未找到游戏角色信息")
            
            current_month = datetime.now().month
            return {
                "gameId": game_list[0].gameId,
                "serverId": game_list[0].serverId,
                "roleId": game_list[0].roleId,
                "userId": game_list[0].userId,
                "reqMonth": f"{current_month:02d}",
            }
        except IndexError:
            raise KurobbsClientException("游戏角色信息不完整")

    def perform_checkin(self) -> Optional[ApiResponse]:
        """执行每日签到（带状态检查）"""
        try:
            game_list = self.get_user_game_list(3)
            if not game_list:
                raise KurobbsClientException("未找到游戏角色信息")
            
            game_info = game_list[0]
            
            # 前置状态检查
            if self.check_sign_status(game_info):
                self.results["daily_checkin"] = "今日已签到，无需重复"
                return None
            
            # 构建签到数据
            current_month = datetime.now().month
            sign_data = {
                "gameId": game_info.gameId,
                "serverId": game_info.serverId,
                "roleId": game_info.roleId,
                "userId": game_info.userId,
                "reqMonth": f"{current_month:02d}",
            }
            
            return self.make_request("sign_in", sign_data)
            
        except IndexError:
            raise KurobbsClientException("游戏角色信息不完整")

    def perform_user_sign(self) -> ApiResponse:
        """执行用户签到"""
        return self.make_request("user_sign", {"gameId": 2})

    def _handle_sign_action(
        self,
        action_name: str,
        action: Callable[[], Optional[ApiResponse]],
        success_msg: str,
        failure_msg: str
    ):
        """增强的签到操作处理"""
        try:
            # 如果结果已在前置检查中设置，直接返回
            if action_name in self.results:
                return
                
            response = action()
            if response is None:  # 表示已处理过结果
                return
                
            if response.success:
                self.results[action_name] = success_msg
            else:
                error_msg = f"{failure_msg}: {response.msg} (code: {response.code})"
                raise KurobbsClientException(error_msg)
                
        except Exception as e:
            self.exceptions.append(e)
            self.results[action_name] = failure_msg

    def execute_sign_workflow(self):
        """执行完整的签到流程"""
        sign_actions = [
            ("daily_checkin", self.perform_checkin, "每日签到成功", "每日签到失败"),
            ("user_signin", self.perform_user_sign, "用户签到成功", "用户签到失败")
        ]

        for name, action, success, failure in sign_actions:
            self._handle_sign_action(name, action, success, failure)

        self._generate_report()

    def _generate_report(self):
        """生成最终报告"""
        if self.results:
            logger.info("签到结果: " + ", ".join(self.results.values()))
        
        if self.exceptions:
            error_details = "\n".join(
                f"{i+1}. {type(e).__name__}: {str(e)}"
                for i, e in enumerate(self.exceptions)
            )
            raise KurobbsClientException(f"遇到{len(self.exceptions)}个错误:\n{error_details}")

    @property
    def notification_message(self) -> str:
        """生成通知消息"""
        return f"{datetime.now().strftime('%Y-%m-%d')} 签到结果: {', '.join(self.results.values())}"

def configure_logger(debug: bool = False):
    """配置日志记录器"""
    logger.remove()
    logger.add(
        sys.stdout,
        format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>",
        level="DEBUG" if debug else "INFO"
    )

def send_notification(message: str, mode: NotificationMode):
    """根据模式发送通知"""
    notification_handlers = {
        NotificationMode.BARK: send_bark_notification,
        NotificationMode.WECHAT_WORK: send_wechat_work_notification,
        NotificationMode.CONSOLE: lambda msg: logger.info(msg)
    }
    
    if handler := notification_handlers.get(mode):
        try:
            handler(message)
        except Exception as e:
            logger.error(f"通知发送失败: {str(e)}")
    else:
        logger.error(f"不支持的通知模式: {mode}")

def parse_env_vars() -> Tuple[str, bool, NotificationMode]:
    """解析环境变量"""
    try:
        token = os.environ["TOKEN"]
        debug = os.environ.get("DEBUG", "false").lower() == "true"
        mode = NotificationMode(os.environ.get("MODE", "wechatWorkApp"))
        return token, debug, mode
    except ValueError as e:
        logger.critical(f"环境变量配置错误: {str(e)}")
        sys.exit(1)
    except KeyError:
        logger.critical("缺少必要的环境变量 TOKEN")
        sys.exit(1)

def main():
    """主执行流程"""
    token, debug, mode = parse_env_vars()
    configure_logger(debug)

    try:
        client = KurobbsClient(token)
        client.execute_sign_workflow()
        
        if client.results:
            send_notification(client.notification_message, mode)

    except KurobbsClientException as e:
        logger.error(f"签到流程失败: {str(e)}")
        send_notification("库街区签到失败", mode)
        sys.exit(1)
    except Exception as e:
        logger.critical(f"未处理的异常: {str(e)}")
        sys.exit(1)

if __name__ == "__main__":
    main()
