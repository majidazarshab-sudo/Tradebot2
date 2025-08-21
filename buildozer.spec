[app]
title = TradeBot
package.name = tradebot
package.domain = org.tradebot
source.dir = .
source.include_exts = py,png,jpg,kv,atlas
version = 0.7
requirements = python3,kivy==2.3.0,telethon==1.35.0,requests==2.32.3
orientation = portrait
fullscreen = 0

[android]
android.api = 31
android.minapi = 21
android.ndk = 25b
android.accept_sdk_license = True
android.archs = arm64-v8a, armeabi-v7a
p4a.branch = stable
android.permissions = INTERNET
