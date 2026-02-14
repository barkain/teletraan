# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_data_files
from PyInstaller.utils.hooks import collect_submodules

datas = []
hiddenimports = ['uvicorn.logging', 'uvicorn.loops.auto', 'uvicorn.protocols.http.auto', 'uvicorn.protocols.websockets.auto', 'uvicorn.lifespan.on', 'uvicorn.protocols.http.h11_impl', 'uvicorn.protocols.http.httptools_impl', 'uvicorn.protocols.websockets.wsproto_impl', 'uvicorn.protocols.websockets.websockets_impl', 'uvicorn.loops.uvloop', 'uvicorn.loops.asyncio', 'aiosqlite', 'fastapi', 'fastapi.middleware', 'fastapi.middleware.cors', 'fastapi.responses', 'fastapi.routing', 'fastapi.security', 'fastapi.websockets', 'pydantic', 'pydantic.deprecated.decorator', 'pydantic._internal._generate_schema', 'pydantic._internal._validators', 'pydantic_settings', 'pydantic_core', 'starlette', 'starlette.middleware', 'starlette.middleware.cors', 'starlette.routing', 'starlette.responses', 'starlette.websockets', 'starlette.formparsers', 'starlette.concurrency', 'starlette.status', 'httpx', 'httpcore', 'h11', 'anyio', 'anyio._backends._asyncio', 'sniffio', 'certifi', 'idna', 'aiohttp', 'multidict', 'yarl', 'async_timeout', 'frozenlist', 'aiosignal', 'yfinance', 'apscheduler', 'apscheduler.schedulers.asyncio', 'apscheduler.triggers.cron', 'fredapi', 'dotenv', 'python_dotenv', 'numpy', 'numpy.core', 'numpy.core._methods', 'numpy.lib', 'numpy.linalg', 'pandas', 'pandas.core.arrays', 'pandas._libs', 'pandas_ta', 'scipy', 'scipy.stats', 'scipy.signal', 'scipy.special', 'requests', 'bs4', 'peewee', 'platformdirs', 'multitasking', 'frozendict', 'pytz', 'tzlocal', 'dateutil', 'six', 'charset_normalizer', 'urllib3', 'sqlalchemy.dialects.sqlite', 'sqlalchemy.dialects.postgresql', 'google.protobuf']
datas += collect_data_files('sqlalchemy')
datas += collect_data_files('pytz')
datas += collect_data_files('certifi')
hiddenimports += collect_submodules('fastapi')
hiddenimports += collect_submodules('starlette')
hiddenimports += collect_submodules('pydantic')
hiddenimports += collect_submodules('pydantic_core')
hiddenimports += collect_submodules('uvicorn')
hiddenimports += collect_submodules('numpy')
hiddenimports += collect_submodules('scipy')
hiddenimports += collect_submodules('pandas')
hiddenimports += collect_submodules('yfinance')
hiddenimports += collect_submodules('requests')
hiddenimports += collect_submodules('bs4')


a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='teletraan-backend',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='teletraan-backend',
)
