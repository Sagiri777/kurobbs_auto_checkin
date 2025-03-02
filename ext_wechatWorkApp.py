import os
import requests
from loguru import logger

def send_wechat_work_notification(message):
    """Send a notification via WeChat Work Application."""
    # 获取企业微信相关配置
    corpid = os.getenv("WECHAT_WORK_CORPID")
    corpsecret = os.getenv("WECHAT_WORK_SECRET")
    agentid = os.getenv("WECHAT_WORK_AGENTID")
    userid = os.getenv("WECHAT_WORK_USERID")

    # 检查环境变量是否配置
    if not all([corpid, corpsecret, agentid, userid]):
        logger.warning("企业微信配置参数缺失，跳过通知发送")
        return

    # 获取access_token
    token_url = f"https://qyapi.weixin.qq.com/cgi-bin/gettoken?corpid={corpid}&corpsecret={corpsecret}"
    try:
        token_response = requests.get(token_url)
        token_response.raise_for_status()
        token_data = token_response.json()
        if token_data.get("errcode") != 0:
            logger.error(f"获取access_token失败: {token_data}")
            return
        access_token = token_data["access_token"]
    except Exception as e:
        logger.error(f"请求access_token时发生异常: {e}")
        return

    # 构造消息内容
    title = "库街区自动签到任务"
    content = f"{title}\n{message}"
    payload = {
        "touser": userid,
        "msgtype": "text",
        "agentid": agentid,
        "text": {
            "content": content
        }
    }

    # 发送应用消息
    send_url = f"https://qyapi.weixin.qq.com/cgi-bin/message/send?access_token={access_token}"
    try:
        send_response = requests.post(send_url, json=payload)
        send_response.raise_for_status()
        result = send_response.json()
        if result.get("errcode") != 0:
            logger.error(f"消息发送失败: {result}")
        else:
            logger.info("企业微信消息推送成功")
    except Exception as e:
        logger.error(f"发送消息时发生异常: {e}")

# 使用示例
# send_wechat_work_notification("签到成功")
