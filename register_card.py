# -*- coding: utf-8 -*-
import binascii
import nfc
import time
import pymysql.cursors
import sys
from datetime import datetime

# Suicaを待ち受けるサイクル（秒）
time_cycle = 1.0
# Suica待ち受けの反応インターバル（秒）
time_interval = 0.2
# タッチされてから次の待ち受けまで無効化する時間（秒）
time_wait = 5

# DB設定情報
conn = pymysql.connect(host="localhost", user="pi", password="raspberry", db="nfc", charset="utf8mb4", cursorclass=pymysql.cursors.DictCursor)

# NFC接続リクエストの準備
# 212F(FeliCa)を設定
target_req_suica = nfc.clf.RemoteTarget("212F")
# 0003(Suica)を設定
# target_req_suica.sensf_req = bytearray.fromhex("0000030000")

# カードをDBに登録する関数
def register_card(idm, name):
    cursor = conn.cursor()
    sql = 'INSERT INTO m_card (idm, name) VALUES (%s, %s)'
    cursor.execute(sql, (idm, name))
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

# メイン関数
print('Suica waiting...')
while True:
    # USB接続されたNFCリーダに接続し、インスタンス化する
    clf = nfc.ContactlessFrontend('usb')
    # Suicaの待ち受けを開始
    # clf.sense( [リモートターゲット], [検索回数], [検索の間隔] )
    target_res = clf.sense(target_req_suica, iterations=int(time_cycle//time_interval) + 1, interval=time_interval)

    # Suica読み取り時
    if target_res != None:
        # IDMを読み込む
        idm = load_idm(clf, target_res)
        print 'カードがタッチされました。IDM = ' + idm

        # 名前を入力してカードマスタに登録
	print '名前を入力してください。'
        name = raw_input('-> ')
        print 'カードを登録中です... NAME = ' + name
        register_card(idm, name)

        print '登録が完了しました！'
        sys.exit()

    clf.close()
