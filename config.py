# config.py 自定义配置,包括阅读次数、推送token的填写
import os
import re
import shlex

"""
可修改区域
默认使用本地值如果不存在从环境变量中获取值
"""

# 阅读次数 默认130次 = 65分钟
READ_NUM = int(os.getenv('READ_NUM') or 130)
# 需要推送时可选，可选pushplus、wxpusher、telegram
PUSH_METHOD = "" or os.getenv('PUSH_METHOD')
# pushplus推送时需填
PUSHPLUS_TOKEN = "" or os.getenv("PUSHPLUS_TOKEN")
# telegram推送时需填
TELEGRAM_BOT_TOKEN = "" or os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = "" or os.getenv("TELEGRAM_CHAT_ID")
# wxpusher推送时需填
WXPUSHER_SPT = "" or os.getenv("WXPUSHER_SPT")
# SeverChan推送时需填
SERVERCHAN_SPT = "" or os.getenv("SERVERCHAN_SPT")


# read接口的bash命令，本地部署时可对应替换headers、cookies
curl_str = os.getenv('WXREAD_CURL_BASH')

# headers、cookies是一个省略模版，本地或者docker部署时对应替换
cookies = {
    'wr_localvid': '28832d2081600c230288079',
    'wr_fp': '4204160285',
    'wr_gid': '268237823',
    'wr_gender': '0',
    'wr_avatar': 'https%3A%2F%2Fres.weread.qq.com%2Fwravatar%2FWV0025-cUHhOPomDQ1dyty6lOulue5%2F0',
    'wr_vid': '369148464',
    'wr_rt': 'web%40ckIgklCmYmK2safNeXA_AL',
    'wr_name': 'booknerd',
    'wr_ql': '0',
    'wr_skey': '1FNVD13T',
}

headers = {
    'accept': 'application/json, text/plain, */*',
    'accept-language': 'zh-CN,zh;q=0.9,en;q=0.8,en-GB;q=0.7,en-US;q=0.6,ko;q=0.5',
    'baggage': 'sentry-environment=production,sentry-release=dev-1730698697208,sentry-public_key=ed67ed71f7804a038e898ba54bd66e44,sentry-trace_id=1ff5a0725f8841088b42f97109c45862',
    'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36 Edg/131.0.0.0',
}


# 书籍
book = [
    "36d322f07186022636daa5e","6f932ec05dd9eb6f96f14b9","43f3229071984b9343f04a4","d7732ea0813ab7d58g0184b8",
    "3d03298058a9443d052d409","4fc328a0729350754fc56d4","a743220058a92aa746632c0","140329d0716ce81f140468e",
    "1d9321c0718ff5e11d9afe8","ff132750727dc0f6ff1f7b5","e8532a40719c4eb7e851cbe","9b13257072562b5c9b1c8d6"
]

# 章节
chapter = [
    "ecc32f3013eccbc87e4b62e","a87322c014a87ff679a21ea","e4d32d5015e4da3b7fbb1fa","16732dc0161679091c5aeb1",
    "8f132430178f14e45fce0f7","c9f326d018c9f0f895fb5e4","45c322601945c48cce2e120","d3d322001ad3d9446802347",
    "65132ca01b6512bd43d90e3","c20321001cc20ad4d76f5ae","c51323901dc51ce410c121b","aab325601eaab3238922e53",
    "9bf32f301f9bf31c7ff0a60","c7432af0210c74d97b01b1c","70e32fb021170efdf2eca12","6f4322302126f4922f45dec"
]

"""
建议保留区域|默认读三体，其它书籍自行测试时间是否增加
"""
data = {
    "appId": "wb182564874603h266381671",
    "b": "ce032b305a9bc1ce0b0dd2a",
    "c": "7f632b502707f6ffaa6bf2e",
    "ci": 27,
    "co": 389,
    "sm": "19聚会《三体》网友的聚会地点是一处僻静",
    "pr": 74,
    "rt": 15,
    "ts": 1744264311434,
    "rn": 466,
    "sg": "2b2ec618394b99deea35104168b86381da9f8946d4bc234e062fa320155409fb",
    "ct": 1744264311,
    "ps": "4ee326507a65a465g015fae",
    "pc": "aab32e207a65a466g010615",
    "s": "36cc0815"
}


def _split_cookie_string(cookie_string):
    result = {}
    if not cookie_string:
        return result
    for cookie in cookie_string.split(';'):
        cookie = cookie.strip()
        if '=' not in cookie:
            continue
        key, value = cookie.split('=', 1)
        result[key.strip()] = value.strip()
    return result


def _parse_curl_with_shlex(curl_command):
    try:
        tokens = shlex.split(curl_command)
    except ValueError:
        return None

    headers_temp = {}
    cookie_string = ''
    index = 0
    while index < len(tokens):
        token = tokens[index]
        value = None
        if token in ('-H', '--header', '-b', '--cookie') and index + 1 < len(tokens):
            value = tokens[index + 1]
            index += 2
        elif token.startswith('-H') and len(token) > 2:
            value = token[2:].strip()
            token = '-H'
            index += 1
        elif token.startswith('--header='):
            value = token.split('=', 1)[1]
            token = '--header'
            index += 1
        elif token.startswith('-b') and len(token) > 2:
            value = token[2:].strip()
            token = '-b'
            index += 1
        elif token.startswith('--cookie='):
            value = token.split('=', 1)[1]
            token = '--cookie'
            index += 1
        else:
            index += 1
            continue

        if token in ('-H', '--header') and value and ':' in value:
            key, header_value = value.split(':', 1)
            key = key.strip()
            header_value = header_value.strip()
            if key.lower() == 'cookie':
                cookie_string = header_value
            else:
                headers_temp[key] = header_value
        elif token in ('-b', '--cookie') and value:
            cookie_string = value

    return headers_temp, _split_cookie_string(cookie_string)


def convert(curl_command):
    """提取bash接口中的headers与cookies
    支持 -H 'Cookie: xxx' 和 -b 'xxx' 两种方式的cookie提取
    """
    parsed = _parse_curl_with_shlex(curl_command)
    if parsed is not None:
        return parsed

    # 兼容旧解析路径
    headers_temp = {}
    for match in re.findall(r"-H ['\"]([^:]+): ([^'\"]+)['\"]", curl_command):
        headers_temp[match[0]] = match[1]
    
    # 从 -H 'Cookie: xxx' 提取
    cookie_header = next((v for k, v in headers_temp.items() 
                         if k.lower() == 'cookie'), '')
    
    # 从 -b 'xxx' 提取
    cookie_b = re.search(r"-b ['\"]([^'\"]+)['\"]", curl_command)
    cookie_string = cookie_b.group(1) if cookie_b else cookie_header
    cookies = _split_cookie_string(cookie_string)
    
    # 移除 headers 中的 Cookie/cookie
    headers = {k: v for k, v in headers_temp.items() 
              if k.lower() != 'cookie'}

    return headers, cookies


def build_curl(headers, cookies, url='https://weread.qq.com/web/book/read'):
    header_parts = []
    for key, value in headers.items():
        if key.lower() == 'cookie':
            continue
        header_parts.append(f"-H {shlex.quote(f'{key}: {value}')}")
    cookie_string = '; '.join(f"{key}={value}" for key, value in cookies.items())
    cookie_part = f"-b {shlex.quote(cookie_string)}" if cookie_string else ''
    parts = ['curl', shlex.quote(url), *header_parts]
    if cookie_part:
        parts.append(cookie_part)
    return ' '.join(parts)


headers, cookies = convert(curl_str) if curl_str else (headers, cookies)
