# -*- coding: utf-8 -*-
import binascii
import nfc
import time
from datetime import datetime
import locale
import json
import requests
from threading import Thread, Timer
import pymysql
import sys
import logging

# デフォルトエンコードをUTF-8にセット
reload(sys)
sys.setdefaultencoding('utf-8')

# ロガーの設定
logging.basicConfig(
    level = logging.DEBUG,
    format = '%(asctime)s %(levelname)s %(funcName)s %(message)s'
)
logger = logging.getLogger(__name__)

# Suicaを待ち受けるサイクル（秒）
time_cycle = 1.0
# Suica待ち受けの反応インターバル（秒）
time_interval = 0.2
# タッチされてから次の待ち受けまで無効化する時間（秒）
time_wait = 5

# Teams Incoming Webhook URI
teams_uri = 'https://outlook.office.com/webhook/uri'
# 日時を投稿する際のテキスト
teams_datetime_text = '\n日時 = '
# 出勤時に投稿されるテキスト
teams_clockin_text = 'さんが出勤しました！！！！！！！'
# 退勤時に投稿されるテキスト
teams_clockout_text = 'さんが退勤しました……'
# 失敗時に投稿されるテキスト
teams_failed_text = '登録されていないカードがタッチされました。カード登録スクリプトを使って登録してください。IDM = '

# テキスト内の日付書式（1900年1月1日(月) 9:05）
datetime_formatter = '%Y年%-m月%-d日(%a) %-k:%M'

# DB設定情報
conn = pymysql.connect(host='localhost', user='pi', password='raspberry', db='nfc', charset='utf8', cursorclass=pymysql.cursors.DictCursor)
# DBにpingを打つ間隔（秒)
mysql_ping_interval = 14400

# NFC接続リクエストの準備
# 212F(FeliCa)を設定
target_req_suica = nfc.clf.RemoteTarget("212F")
# 0003(Suica)を設定
# target_req_suica.sensf_req = bytearray.fromhex("0000000000")

# IDMから所有者名を取得する関数
def load_holder(idm):
    cursor = conn.cursor()
    sql = 'SELECT card_id, name FROM m_card WHERE idm = %s'
    cursor.execute(sql, (idm))
    holder = cursor.fetchone()
    return holder

# カードIDから最後にタッチされた際の勤怠状況を取得する関数
def load_attendance_type(card_id):
    cursor = conn.cursor()
    sql = 'SELECT attendance_type FROM l_attendance WHERE card_id = %s ORDER BY creation_time DESC LIMIT 1'
    cursor.execute(sql, (card_id, ))
    last_attendance_type = cursor.fetchone()
    return last_attendance_type

# 勤怠状況を登録する関数
def save_attendance(card_id, attendance_type):
    cursor = conn.cursor()
    sql = 'INSERT INTO l_attendance (card_id, attendance_type) VALUES (%s, %s)'
    cursor.execute(sql, (card_id, attendance_type))
    conn.commit()

# タッチされたSuicaのIDMを取得する関数
def load_idm(clf, target_res):
    # 読み取ったカード情報を取得
    tag = nfc.tag.activate_tt3(clf, target_res)
    tag.sys = 3

    # IDMを取り出す
    idm = binascii.hexlify(tag.idm)
    print('Suica detected. idm = ' + idm)
    return idm

# 認証成功時、Teamsに投稿する関数
def post_successed(name, attendance_type, now):
    # 勤怠情報によって投稿するメッセージを分ける
    message = teams_clockin_text if attendance_type == 1 else teams_clockout_text

    # 日本語の曜日表記を使えるようにする
    locale.setlocale(locale.LC_TIME, 'ja_JP.UTF-8')
    datetime = now.strftime(datetime_formatter)

    # リクエストボディを作成
    text = {
        'text': name+ message + teams_datetime_text + datetime
    }
    data = json.dumps(text)

    # リクエストを送信
    requests.post(teams_uri, data)

# 認証失敗時、Teamsに投稿する関数
def post_failed(idm, now):
    # 日本語の曜日表記を使えるようにする
    locale.setlocale(locale.LC_TIME, 'ja_JP.UTF-8')
    datetime = now.strftime(datetime_formatter)

    # リクエストボディを作成
    text = {
        'text': teams_failed_text + idm + teams_datetime_text + datetime
    }
    data = json.dumps(text)

    # リクエストを送信
    requests.post(teams_uri, data)

# タイムアウト防止のため、定期的にMySQLへクエリを発行する関数
def ping_mysql():
    cursor = conn.cursor()
    sql = 'SELECT 1'
    cursor.execute(sql)
    logger.debug('MySQLにpingを打ちました')

# メイン関数
logger.debug('Suica waiting...')
# 最後にMySQLにpingを打った日時
last_ping_datetime = datetime.now()
# USB接続されたNFCリーダに接続し、インスタンス化する
# TODO:どこかでclf.close()?
clf = nfc.ContactlessFrontend('usb')

while True:
    # Suicaの待ち受けを開始
    # clf.sense( [リモートターゲット], [検索回数], [検索の間隔] )
    target_res = clf.sense(target_req_suica, iterations=int(time_cycle//time_interval) + 1, interval=time_interval)

    # 処理日時
    now = datetime.now()

    # Suica読み取り時の動作
    if target_res != None:
        # IDMを取得
        idm = load_idm(clf, target_res)
        # IDMがDBに登録されているか確認
        holder = load_holder(idm)
        # 取得できなかった場合は失敗テキストをTeamsに投稿して待機状態に戻る
        if holder is None:
            logger.info('カードが登録されていません。idm = ' + idm )
            post_failed(idm, now)

        # 取得できた場合は勤怠メッセージをTeamsに投稿
        else:
            logger.info('認証成功 idm = ' + idm)
            # 最後の勤怠種類を読み込む
            last_attendance_type = load_attendance_type(holder.get('card_id'))
            # 登録する勤怠種類の初期値を1:出勤とし、最後の勤怠種類が取得できたかチェック
            attendance_type = 1
            if last_attendance_type is not None:
                # 「出勤」の場合は「退勤」、「退勤」の場合は「出勤」を登録する
                attendance_type = 2 if last_attendance_type.get('attendance_type') == 1 else 1
            save_attendance(holder.get('card_id'), attendance_type)
            # Teamsに勤怠メッセージを投稿
            post_successed(holder.get('name'), attendance_type, now)

        logger.debug('sleep ' + str(time_wait) + ' seconds')
        time.sleep(time_wait)

    # MySQLのlost connection防止のため、定期的にpingを打つ
    delta = now - last_ping_datetime
    if delta.total_seconds() >= mysql_ping_interval:
        ping_mysql()
        # 最終ping日時を現在日時に更新
        last_ping_datetime = now

