import os
import sys
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional

import requests
from loguru import logger
from pydantic import BaseModel, Field

from ext_bark import send_bark_notification
from ext_wechatWorkApp import send_wechat_work_notification

mode = "wechatWorkApp"

class Response(BaseModel):
    code: int = Field(..., alias="code", description="返回值")
    msg: str = Field(..., alias="msg", description="提示信息")
    success: Optional[bool] = Field(None, alias="success", description="token有时才有")
    data: Optional[Any] = Field(None, alias="data", description="请求成功才有")


class KurobbsClientException(Exception):
    """Custom exception for Kurobbs client errors."""
    pass


class KurobbsClient:
    FIND_ROLE_LIST_API_URL = "https://api.kurobbs.com/user/role/findRoleList"
    SIGN_URL = "https://api.kurobbs.com/encourage/signIn/v2"
    USER_SIGN_URL = "https://api.kurobbs.com/user/signIn"

    def __init__(self, token: str):
        self.token = token
        self.result: Dict[str, str] = {}
        self.exceptions: List[Exception] = []

    def get_headers(self) -> Dict[str, str]:
        """Get the headers required for API requests."""
        return {
        'User-Agent': "Mozilla/5.0 (iPhone; CPU iPhone OS 16_2 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko)  KuroGameBox/2.4.0",
        'Accept': "application/json, text/plain, */*",
        'source': "ios",
        'accept-language': "zh-CN,zh-Hans;q=0.9",
        'token': self.token,
        'origin': "https://web-static.kurobbs.com"
        }

    def make_request(self, url: str, data: Dict[str, Any]) -> Response:
        """Make a POST request to the specified URL with the given data."""
        headers = self.get_headers()
        logger.debug(f"Making request to: {url}")
        logger.debug(f"Request headers: {headers}")
        logger.debug(f"Request data: {data}")
        
        response = requests.post(url, headers=headers, data=data)
        logger.debug(f"Response status code: {response.status_code}")
        logger.debug(f"Response content: {response.content.decode()}")
        
        res = Response.model_validate_json(response.content)
        logger.debug(f"Parsed response: {res.model_dump_json(indent=2)}")
        return res

    def get_user_game_list(self, game_id: int) -> List[Dict[str, Any]]:
        """Get the list of games for the user."""
        logger.debug(f"Getting user game list for game_id: {game_id}")
        data = {"gameId": game_id}
        res = self.make_request(self.FIND_ROLE_LIST_API_URL, data)
        logger.debug(f"User game list response data: {res.data}")
        return res.data

    def checkin(self) -> Response:
        """Perform the check-in operation."""
        logger.debug("Starting check-in process")
        user_game_list = self.get_user_game_list(3)
        
        date = datetime.now().month
        data = {
            "gameId": user_game_list[0].get("gameId", 2),
            "serverId": user_game_list[0].get("serverId", None),
            "roleId": user_game_list[0].get("roleId", 0),
            "userId": user_game_list[0].get("userId", 0),
            "reqMonth": f"{date:02d}",
        }
        logger.debug(f"Check-in data prepared: {data}")
        return self.make_request(self.SIGN_URL, data)

    def sign_in(self) -> Response:
        """Perform the sign-in operation."""
        logger.debug("Starting sign-in process")
        return self.make_request(self.USER_SIGN_URL, {"gameId": 2})

    def _process_sign_action(
        self,
        action_name: str,
        action_method: Callable[[], Response],
        success_message: str,
        failure_message: str,
    ):
        """
        Handle the common logic for sign-in actions.

        :param action_name: The name of the action (used to store the result).
        :param action_method: The method to call for the sign-in action.
        :param success_message: The message to log on success.
        :param failure_message: The message to log on failure.
        """
        logger.debug(f"Processing sign action: {action_name}")
        try:
            resp = action_method()
            if resp.success:
                logger.debug(f"{action_name} successful: {success_message}")
                self.result[action_name] = success_message
            else:
                logger.debug(f"{action_name} failed: {failure_message}")
                self.exceptions.append(KurobbsClientException(failure_message))
        except Exception as e:
            logger.exception(f"Error during {action_name}")
            self.exceptions.append(e)

    def start(self):
        """Start the sign-in process."""
        self._process_sign_action(
            action_name="checkin",
            action_method=self.checkin,
            success_message="签到奖励签到成功",
            failure_message="签到奖励签到失败",
        )

        self._process_sign_action(
            action_name="sign_in",
            action_method=self.sign_in,
            success_message="社区签到成功",
            failure_message="社区签到失败",
        )

        self._log()

    @property
    def msg(self):
        return ", ".join(self.result.values()) + "!"

    def _log(self):
        """Log the results and raise exceptions if any."""
        if msg := self.msg:
            logger.info(msg)
        if self.exceptions:
            raise KurobbsClientException(", ".join(map(str, self.exceptions)))


def configure_logger(debug: bool = False):
    """Configure the logger based on the debug mode."""
    logger.remove()  # Remove default logger configuration
    log_level = "DEBUG" if debug else "INFO"
    format_string = "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>"
    logger.add(sys.stdout, level=log_level, format=format_string)


def main():
    """Main function to handle command-line arguments and start the sign-in process."""
    token = os.getenv("TOKEN")
    debug = os.getenv("DEBUG", False)
    mode = os.getenv("MODE", "wechatWorkApp")
    configure_logger(debug=debug)

    try:
        kurobbs = KurobbsClient(token)
        kurobbs.start()
        if kurobbs.msg:
            if mode == "bark":
                send_bark_notification(kurobbs.msg)
            elif mode == "wechatWorkApp":
                send_wechat_work_notification(kurobbs.msg)
            else:
                logger.info(kurobbs.msg)
    except KurobbsClientException as e:
        logger.error(str(e), exc_info=False)
        if mode == "bark":
            send_bark_notification(kurobbs.msg)
        elif mode == "wechatWorkApp":
            send_wechat_work_notification(kurobbs.msg)
        else:
            logger.info(kurobbs.msg)
        sys.exit(1)
    except Exception as e:
        logger.error(f"An unexpected error occurred: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()