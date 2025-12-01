import asyncio
import time
import httpx
import json
from collections import defaultdict
from functools import wraps
from flask import Flask, request, jsonify, render_template_string
from flask_cors import CORS
from cachetools import TTLCache
from typing import Tuple
from proto import FreeFire_pb2, main_pb2, AccountPersonalShow_pb2
from google.protobuf import json_format, message
from google.protobuf.message import Message
from Crypto.Cipher import AES
import base64
import random

# === Settings ===
MAIN_KEY = base64.b64decode('WWcmdGMlREV1aDYlWmNeOA==')
MAIN_IV = base64.b64decode('Nm95WkRyMjJFM3ljaGpNJQ==')
RELEASEVERSION = "OB51"
USERAGENT = "Dalvik/2.1.0 (Linux; U; Android 13; CPH2095 Build/RKQ1.211119.001)"
SUPPORTED_REGIONS = {"IND", "BR", "US", "SAC", "NA", "SG", "RU", "ID", "TW", "VN", "TH", "ME", "PK", "CIS", "BD", "EUROPE"}

# === Flask App Setup ===
app = Flask(__name__)
CORS(app)
cache = TTLCache(maxsize=100, ttl=300)
cached_tokens = defaultdict(dict)

# === Helper Functions ===
def pad(text: bytes) -> bytes:
    padding_length = AES.block_size - (len(text) % AES.block_size)
    return text + bytes([padding_length] * padding_length)

def aes_cbc_encrypt(key: bytes, iv: bytes, plaintext: bytes) -> bytes:
    aes = AES.new(key, AES.MODE_CBC, iv)
    return aes.encrypt(pad(plaintext))

def decode_protobuf(encoded_data: bytes, message_type: message.Message) -> message.Message:
    instance = message_type()
    instance.ParseFromString(encoded_data)
    return instance

async def json_to_proto(json_data: str, proto_message: Message) -> bytes:
    json_format.ParseDict(json.loads(json_data), proto_message)
    return proto_message.SerializeToString()

def get_account_credentials(region: str) -> str:
    r = region.upper()
    if r == "IND":
        return "uid=3692279677&password=473AFFEF67F708CBB0962A958BB2809DA0843EA41BDB70D738FD9527EA04B27B"
    elif r in {"BR", "US", "SAC", "NA"}:
        return "uid=4317703753&password=BY_MERCY-PMKPMAAGV-HACKED"
    elif r == "VN":
        return "uid=3686689562&password=AD9C4A2B51A749481913F72A36F68A9F231520E9AC29B244DB47A64FD7353A12"
    elif r == "SG":
        return "uid=3692265171&password=A2A5E3C252A35B2BB30698BD1469A759417A68A069CF6980ED959EB01D352E28"
    elif r == "ID":
        return "uid=3692307512&password=4AA06E1DB3F998ABDBDA74578D26B0C84700EC5C079751E7C8F1626048DDBCAE"
    elif r == "TH":
        return "uid=3692333198&password=0ED64C5A89E09B8BE538829B0304FE5F5F7EA3BBE645A341C73ECA49143D2211"
    elif r == "TW":
        return "uid=3692312456&password=1A062FD700DA8F826AF84A37EE2B62121B79516AF71666949C72FFF42D1C554A"
    else:
        try:
            with open("accounts.txt", "r") as f:
                lines = [line.strip() for line in f if line.strip()]
                if not lines:
                    raise ValueError("File accounts.txt trống.")
                uid, password = random.choice(lines).split()
                return f"uid={uid}&password={password}"
        except Exception as e:
            return f"ERROR: {e}"

# === Token Generation ===
async def get_access_token(account: str):
    url = "https://ffmconnect.live.gop.garenanow.com/oauth/guest/token/grant"
    payload = account + "&response_type=token&client_type=2&client_secret=2ee44819e9b4598845141067b281621874d0d5d7af9d8f7e00c1e54715b7d1e3&client_id=100067"
    headers = {'User-Agent': USERAGENT, 'Connection': "Keep-Alive", 'Accept-Encoding': "gzip", 'Content-Type': "application/x-www-form-urlencoded"}
    async with httpx.AsyncClient() as client:
        resp = await client.post(url, data=payload, headers=headers)
        data = resp.json()
        return data.get("access_token", "0"), data.get("open_id", "0")

async def create_jwt(region: str):
    account = get_account_credentials(region)
    token_val, open_id = await get_access_token(account)
    body = json.dumps({"open_id": open_id, "open_id_type": "4", "login_token": token_val, "orign_platform_type": "4"})
    proto_bytes = await json_to_proto(body, FreeFire_pb2.LoginReq())
    payload = aes_cbc_encrypt(MAIN_KEY, MAIN_IV, proto_bytes)
    url = "https://loginbp.ggblueshark.com/MajorLogin"
    headers = {'User-Agent': USERAGENT, 'Connection': "Keep-Alive", 'Accept-Encoding': "gzip",
               'Content-Type': "application/octet-stream", 'Expect': "100-continue", 'X-Unity-Version': "2018.4.11f1",
               'X-GA': "v1 1", 'ReleaseVersion': RELEASEVERSION}
    async with httpx.AsyncClient() as client:
        resp = await client.post(url, data=payload, headers=headers)
        msg = json.loads(json_format.MessageToJson(decode_protobuf(resp.content, FreeFire_pb2.LoginRes)))
        cached_tokens[region] = {
            'token': f"Bearer {msg.get('token','0')}",
            'region': msg.get('lockRegion','0'),
            'server_url': msg.get('serverUrl','0'),
            'expires_at': time.time() + 25200
        }

async def initialize_tokens():
    tasks = [create_jwt(r) for r in SUPPORTED_REGIONS]
    await asyncio.gather(*tasks)

async def refresh_tokens_periodically():
    while True:
        await asyncio.sleep(25200)
        await initialize_tokens()

async def get_token_info(region: str) -> Tuple[str,str,str]:
    info = cached_tokens.get(region)
    if info and time.time() < info['expires_at']:
        return info['token'], info['region'], info['server_url']
    await create_jwt(region)
    info = cached_tokens[region]
    return info['token'], info['region'], info['server_url']

async def GetAccountInformation(uid, unk, region, endpoint):
    region = region.upper()
    if region not in SUPPORTED_REGIONS:
        raise ValueError(f"Unsupported region: {region}")
    payload = await json_to_proto(json.dumps({'a': uid, 'b': unk}), main_pb2.GetPlayerPersonalShow())
    data_enc = aes_cbc_encrypt(MAIN_KEY, MAIN_IV, payload)
    token, lock, server = await get_token_info(region)
    headers = {'User-Agent': USERAGENT, 'Connection': "Keep-Alive", 'Accept-Encoding': "gzip",
               'Content-Type': "application/octet-stream", 'Expect': "100-continue",
               'Authorization': token, 'X-Unity-Version': "2018.4.11f1", 'X-GA': "v1 1",
               'ReleaseVersion': RELEASEVERSION}
    async with httpx.AsyncClient() as client:
        resp = await client.post(server+endpoint, data=data_enc, headers=headers)
        return json.loads(json_format.MessageToJson(decode_protobuf(resp.content, AccountPersonalShow_pb2.AccountPersonalShowInfo)))

# === Caching Decorator ===
def cached_endpoint(ttl=300):
    def decorator(fn):
        @wraps(fn)
        def wrapper(*a, **k):
            key = (request.path, tuple(request.args.items()))
            if key in cache:
                return cache[key]
            res = fn(*a, **k)
            cache[key] = res
            return res
        return wrapper
    return decorator
    
# --- HTML + JS para calcular XP e % ---
html_template = """
<!DOCTYPE html>
<html lang="pt">
<head>
<meta charset="UTF-8">
<title>XP Free Fire</title>
<style>
    body { font-family: Arial; padding: 20px; background: #f5f5f5; }
    .box { background: white; padding: 20px; border-radius: 10px; max-width: 420px; margin: auto; }
    input, select, button { width: 100%; padding: 10px; margin-top: 10px; }
    #barBox { width: 100%; background: #ddd; height: 20px; margin-top: 10px; border-radius: 6px; }
    #bar { height: 100%; width: 0%; background: #4caf50; transition: 0.5s; border-radius: 6px; }
    .result { margin-top: 15px; background: #eee; padding: 10px; border-radius: 6px; }
</style>
</head>
<body>
<div class="box">
    <h2>Calculadora de XP Free Fire</h2>

    <label>UID do jogador:</label>
    <input id="uid" placeholder="Digite o UID">

    <label>Região:</label>
    <select id="region">
        <option value="BR">BR</option>
        <option value="US">US</option>
        <option value="IND">IND</option>
    </select>

    <label>Nível desejado:</label>
    <select id="targetLevel"></select>

    <button onclick="calcular()">Calcular</button>

    <div class="result" id="res"></div>
    <div id="barBox"><div id="bar"></div></div>
</div>

<script>
const xpTable = {
1:0,2:1000,3:3000,4:6000,5:10000,6:15000,7:21000,8:28000,9:36000,10:45000,
11:55000,12:66000,13:78000,14:91000,15:105000,16:120000,17:136000,18:153000,
19:171000,20:190000,21:210000,22:231000,23:253000,24:276000,25:300000,26:325000,
27:351000,28:378000,29:406000,30:435000,31:465000,32:496000,33:528000,34:561000,
35:595000,36:630000,37:666000,38:703000,39:741000,40:780000,41:820000,42:861000,
43:903000,44:946000,45:990000,46:1035000,47:1081000,48:1128000,49:1176000,50:1225000,
51:1275000,52:1326000,53:1378000,54:1431000,55:1485000,56:1540000,57:1596000,58:1653000,
59:1711000,60:1770000,61:1830000,62:1891000,63:1953000,64:2016000,65:2080000,66:2145000,
67:2211000,68:2278000,69:2346000,70:2415000,71:2485000,72:2556000,73:2628000,74:2701000,
75:2775000,76:2850000,77:2926000,78:3003000,79:3081000,80:3160000,81:3240000,82:3321000,
83:3403000,84:3486000,85:3570000,86:3655000,87:3741000,88:3828000,89:3916000,90:4005000,
91:4095000,92:4186000,93:4278000,94:4371000,95:4465000,96:4560000,97:4656000,98:4753000,
99:4851000,100:32032284
};

// Preencher select de níveis
let sel = document.getElementById("targetLevel");
for (let i=2;i<=100;i++){ sel.innerHTML += `<option value="${i}">${i}</option>`; }

async function calcular(){
    let uid = document.getElementById("uid").value;
    let region = document.getElementById("region").value;
    let target = parseInt(document.getElementById("targetLevel").value);
    let res = document.getElementById("res");
    let bar = document.getElementById("bar");

    if(!uid){ res.innerHTML="Digite o UID!"; return; }

    try{
        // Chama a API real que você já tem
        let r = await fetch(`/player-info?uid=${uid}&region=${region}`);
        let data = await r.json();
        let xpAtual = data.basicInfo.exp;

        let xpNec = xpTable[target];
        let falta = xpNec - xpAtual;
        let porc = (xpAtual / xpNec)*100;

        if(falta<0){ falta=0; porc=100; }

        res.innerHTML = `<b>XP Atual:</b> ${xpAtual.toLocaleString()}<br>
                         <b>XP Necessário (${target}):</b> ${xpNec.toLocaleString()}<br>
                         <b>XP Faltando:</b> ${falta.toLocaleString()}<br>
                         <b>Progresso:</b> ${porc.toFixed(2)}%`;
        bar.style.width = porc + "%";
    } catch(e){
        console.error(e);
        res.innerHTML="Erro ao acessar API.";
    }
}
</script>
</body>
</html>
"""

@app.route('/')
def index():
    return render_template_string(html_template)

# === Flask Routes ===
@app.route('/player-info')
@cached_endpoint()
def get_account_info():
    region = request.args.get('region')
    uid = request.args.get('uid')

    # Pehle basic validation
    if not uid:
        return jsonify({"error": "Please provide UID."}), 400

    if not region:
        return jsonify({"error": "Please provide REGION."}), 400

    try:
        # API call
        return_data = asyncio.run(GetAccountInformation(uid, "7", region, "/GetPlayerPersonalShow"))

        # Agar data mila toh usko beautify karke bhejo
        formatted_json = json.dumps(return_data, indent=2, ensure_ascii=False)
        return formatted_json, 200, {'Content-Type': 'application/json; charset=utf-8'}

    except Exception as e:
        # Agar koi error aaye toh yeh catch karega
        return jsonify({"error": "Invalid UID or Region. Please check and try again."}), 500

@app.route('/refresh', methods=['GET','POST'])
def refresh_tokens_endpoint():
    try:
        asyncio.run(initialize_tokens())
        return jsonify({'message':'Tokens refreshed for all regions.'}),200
    except Exception as e:
        return jsonify({'error': f'Refresh failed: {e}'}),500

# === Startup ===
async def startup():
    await initialize_tokens()
    asyncio.create_task(refresh_tokens_periodically())

if __name__ == '__main__':
    asyncio.run(startup())
    app.run(host='0.0.0.0', port=5000, debug=True)
