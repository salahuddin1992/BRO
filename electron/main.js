/**
 * Helen WiFi - Electron Main Process
 * Native desktop window + System Tray + Notifications + Auto-Update + Deep Linking
 */
const { app, BrowserWindow, Tray, Menu, nativeImage, Notification, ipcMain, dialog, shell, session: electronSession } = require('electron');
const path = require('path');
const { spawn } = require('child_process');
const net = require('net');
const fs = require('fs');

// Configuration
const APP_NAME = 'Helen WiFi';
const SERVER_PORT = 8400;
const SERVER_URL = `https://127.0.0.1:${SERVER_PORT}`;
const PROTOCOL_NAME = 'bro';

let mainWindow = null;
let tray = null;
let serverProcess = null;
let isQuitting = false;
let serverReady = false;
let autoUpdater = null;

// ========== Deep Linking Protocol ==========
if (process.defaultApp) {
    if (process.argv.length >= 2) {
        app.setAsDefaultProtocolClient(PROTOCOL_NAME, process.execPath, [path.resolve(process.argv[1])]);
    }
} else {
    app.setAsDefaultProtocolClient(PROTOCOL_NAME);
}

// ========== Auto-Updater ==========
function initAutoUpdater() {
    try {
        const { autoUpdater: electronAutoUpdater } = require('electron-updater');
        autoUpdater = electronAutoUpdater;
        autoUpdater.autoDownload = false;
        autoUpdater.autoInstallOnAppQuit = true;

        autoUpdater.on('update-available', (info) => {
            showNotification(APP_NAME, `تحديث جديد متوفر: ${info.version}`);
            if (mainWindow) {
                mainWindow.webContents.send('update-available', info);
            }
            dialog.showMessageBox(mainWindow, {
                type: 'info',
                title: 'تحديث جديد',
                message: `الإصدار ${info.version} متوفر. هل تريد تنزيله؟`,
                buttons: ['تنزيل', 'لاحقاً'],
                defaultId: 0,
            }).then(result => {
                if (result.response === 0) {
                    autoUpdater.downloadUpdate();
                }
            });
        });

        autoUpdater.on('update-downloaded', () => {
            dialog.showMessageBox(mainWindow, {
                type: 'info',
                title: 'التحديث جاهز',
                message: 'تم تنزيل التحديث. سيتم تثبيته عند إعادة التشغيل.',
                buttons: ['إعادة التشغيل الآن', 'لاحقاً'],
                defaultId: 0,
            }).then(result => {
                if (result.response === 0) {
                    autoUpdater.quitAndInstall();
                }
            });
        });

        autoUpdater.on('error', (err) => {
            console.log('Auto-updater error:', err.message);
        });

        // Check for updates after startup
        setTimeout(() => {
            autoUpdater.checkForUpdates().catch(() => {});
        }, 5000);
    } catch (e) {
        console.log('Auto-updater not available (dev mode):', e.message);
    }
}

// ========== Auto-Start ==========
function setAutoStart(enable) {
    app.setLoginItemSettings({
        openAtLogin: enable,
        openAsHidden: true,
        path: process.execPath,
        args: ['--hidden'],
    });
    settings.autoStart = enable;
    saveSettings();
}

// ========== Settings Store ==========
let settings = {
    minimizeToTray: true,
    startMinimized: false,
    notifications: true,
    autoStart: false,
    windowBounds: { width: 1200, height: 800 },
};

const settingsPath = path.join(app.getPath('userData'), 'settings.json');

function loadSettings() {
    try {
        if (fs.existsSync(settingsPath)) {
            const data = fs.readFileSync(settingsPath, 'utf8');
            settings = { ...settings, ...JSON.parse(data) };
        }
    } catch (e) {
        console.error('Failed to load settings:', e);
    }
}

function saveSettings() {
    try {
        fs.writeFileSync(settingsPath, JSON.stringify(settings, null, 2));
    } catch (e) {
        console.error('Failed to save settings:', e);
    }
}

// ========== Server Management ==========
function getServerPath() {
    const isPackaged = app.isPackaged;
    if (isPackaged) {
        const resourcePath = process.resourcesPath;
        const ext = process.platform === 'win32' ? '.exe' : '';
        return path.join(resourcePath, 'server', `HelenWiFi${ext}`);
    }
    // Development mode - use Python directly
    return null;
}

function startServer() {
    return new Promise((resolve, reject) => {
        const serverPath = getServerPath();

        if (serverPath && fs.existsSync(serverPath)) {
            // Production: run bundled executable
            // Pass userData as runtime path so uploads/DB/certs go to a writable location
            // (the EXE directory may be read-only, e.g. inside Program Files)
            const runtimePath = app.getPath('userData');
            console.log(`Starting server: ${serverPath}  (runtime: ${runtimePath})`);
            serverProcess = spawn(serverPath, ['--port', String(SERVER_PORT), '--verbose'], {
                cwd: path.dirname(serverPath),
                stdio: ['pipe', 'pipe', 'pipe'],
                env: { ...process.env, BRO_RUNTIME_PATH: runtimePath },
            });
        } else {
            // Development: run Python directly
            const projectRoot = path.resolve(__dirname, '..');
            const runPy = path.join(projectRoot, 'run.py');
            console.log(`Starting dev server: python ${runPy}`);
            serverProcess = spawn('python3', [runPy, '--port', String(SERVER_PORT), '--verbose'], {
                cwd: projectRoot,
                stdio: ['pipe', 'pipe', 'pipe'],
            });
        }

        serverProcess.stdout.on('data', (data) => {
            const output = data.toString();
            console.log(`[Server] ${output}`);
            if (output.includes('Client') || output.includes(String(SERVER_PORT))) {
                serverReady = true;
            }
        });

        serverProcess.stderr.on('data', (data) => {
            console.error(`[Server Error] ${data}`);
        });

        serverProcess.on('error', (err) => {
            console.error('Failed to start server:', err);
            reject(err);
        });

        serverProcess.on('exit', (code) => {
            console.log(`Server exited with code ${code}`);
            serverProcess = null;
            if (!isQuitting) {
                showNotification('Helen WiFi', 'توقف السيرفر بشكل غير متوقع');
            }
        });

        // Wait for server to be ready
        waitForServer(SERVER_PORT, 30000)
            .then(() => {
                serverReady = true;
                resolve();
            })
            .catch(reject);
    });
}

function waitForServer(port, timeout) {
    return new Promise((resolve, reject) => {
        const startTime = Date.now();

        function tryConnect() {
            if (Date.now() - startTime > timeout) {
                reject(new Error('Server startup timeout'));
                return;
            }

            const client = new net.Socket();
            client.setTimeout(1000);

            client.connect(port, '127.0.0.1', () => {
                client.destroy();
                resolve();
            });

            client.on('error', () => {
                client.destroy();
                setTimeout(tryConnect, 500);
            });

            client.on('timeout', () => {
                client.destroy();
                setTimeout(tryConnect, 500);
            });
        }

        tryConnect();
    });
}

function stopServer() {
    if (serverProcess) {
        console.log('Stopping server...');
        if (process.platform === 'win32') {
            spawn('taskkill', ['/pid', String(serverProcess.pid), '/f', '/t']);
        } else {
            serverProcess.kill('SIGTERM');
            setTimeout(() => {
                if (serverProcess) {
                    serverProcess.kill('SIGKILL');
                }
            }, 5000);
        }
    }
}

// ========== Window Management ==========
function createWindow() {
    const { width, height, x, y } = settings.windowBounds;

    mainWindow = new BrowserWindow({
        width,
        height,
        x,
        y,
        minWidth: 800,
        minHeight: 600,
        title: APP_NAME,
        icon: getIconPath(),
        backgroundColor: '#0a0a1a',
        autoHideMenuBar: true,
        show: !settings.startMinimized,
        webPreferences: {
            preload: path.join(__dirname, 'preload.js'),
            nodeIntegration: false,
            contextIsolation: true,
            spellcheck: true,
            sandbox: true,
        },
    });

    // Remove default menu
    mainWindow.setMenuBarVisibility(false);

    // Set Content Security Policy
    mainWindow.webContents.session.webRequest.onHeadersReceived((details, callback) => {
        callback({
            responseHeaders: {
                ...details.responseHeaders,
                'Content-Security-Policy': [
                    "default-src 'self' https://127.0.0.1:* https://localhost:* http://127.0.0.1:* http://localhost:*; " +
                    "script-src 'self' 'unsafe-inline' https://127.0.0.1:* https://localhost:* http://127.0.0.1:* http://localhost:*; " +
                    "style-src 'self' 'unsafe-inline'; " +
                    "img-src 'self' data: blob: https://127.0.0.1:* https://localhost:* http://127.0.0.1:* http://localhost:*; " +
                    "media-src 'self' blob: mediastream:; " +
                    "connect-src 'self' wss://127.0.0.1:* wss://localhost:* ws://127.0.0.1:* ws://localhost:* https://127.0.0.1:* https://localhost:* http://127.0.0.1:* http://localhost:*; " +
                    "font-src 'self';"
                ],
            },
        });
    });

    // Accept self-signed certificates from the local server
    mainWindow.webContents.on('certificate-error', (event, url, error, certificate, callback) => {
        if (url.startsWith(`https://127.0.0.1:${SERVER_PORT}`) || url.startsWith(`https://localhost:${SERVER_PORT}`)) {
            event.preventDefault();
            callback(true);
        } else {
            callback(false);
        }
    });

    // Load the app
    mainWindow.loadURL(`${SERVER_URL}/client`);

    // Handle window events
    mainWindow.on('close', (event) => {
        if (!isQuitting && settings.minimizeToTray) {
            event.preventDefault();
            mainWindow.hide();
            if (process.platform === 'darwin') {
                app.dock.hide();
            }
            return;
        }
        // Save window bounds
        settings.windowBounds = mainWindow.getBounds();
        saveSettings();
    });

    mainWindow.on('resize', () => {
        if (!mainWindow.isMinimized()) {
            settings.windowBounds = mainWindow.getBounds();
        }
    });

    mainWindow.on('move', () => {
        settings.windowBounds = mainWindow.getBounds();
    });

    // Restrict navigation to local server only (prevent phishing/redirect attacks)
    mainWindow.webContents.on('will-navigate', (event, url) => {
        const allowed = url.startsWith(SERVER_URL) ||
                        url.startsWith('http://127.0.0.1:') ||
                        url.startsWith('https://127.0.0.1:') ||
                        url.startsWith('http://localhost:') ||
                        url.startsWith('https://localhost:');
        if (!allowed) {
            event.preventDefault();
            shell.openExternal(url);
        }
    });

    // Handle new window requests (open in default browser)
    mainWindow.webContents.setWindowOpenHandler(({ url }) => {
        if (url.startsWith('http')) {
            shell.openExternal(url);
        }
        return { action: 'deny' };
    });

    // Inject custom CSS for desktop feel
    mainWindow.webContents.on('did-finish-load', () => {
        mainWindow.webContents.insertCSS(`
            /* Desktop-specific enhancements */
            body { -webkit-app-region: no-drag; }
            ::-webkit-scrollbar { width: 8px; }
            ::-webkit-scrollbar-track { background: rgba(255,255,255,0.02); }
            ::-webkit-scrollbar-thumb { background: rgba(255,255,255,0.1); border-radius: 4px; }
            ::-webkit-scrollbar-thumb:hover { background: rgba(255,255,255,0.2); }
        `);
    });
}

// ========== System Tray ==========
function createTray() {
    const icon = getTrayIcon();
    tray = new Tray(icon);

    const contextMenu = Menu.buildFromTemplate([
        {
            label: 'فتح Helen WiFi',
            click: () => {
                if (mainWindow) {
                    mainWindow.show();
                    mainWindow.focus();
                    if (process.platform === 'darwin') {
                        app.dock.show();
                    }
                }
            },
        },
        { type: 'separator' },
        {
            label: 'لوحة التحكم',
            click: () => {
                shell.openExternal(`${SERVER_URL}/admin`);
            },
        },
        { type: 'separator' },
        {
            label: 'الإشعارات',
            type: 'checkbox',
            checked: settings.notifications,
            click: (item) => {
                settings.notifications = item.checked;
                saveSettings();
            },
        },
        {
            label: 'تصغير لشريط المهام',
            type: 'checkbox',
            checked: settings.minimizeToTray,
            click: (item) => {
                settings.minimizeToTray = item.checked;
                saveSettings();
            },
        },
        {
            label: 'بدء تشغيل مع النظام',
            type: 'checkbox',
            checked: settings.autoStart,
            click: (item) => {
                setAutoStart(item.checked);
            },
        },
        { type: 'separator' },
        {
            label: 'إعادة تشغيل السيرفر',
            click: async () => {
                stopServer();
                await new Promise(r => setTimeout(r, 2000));
                try {
                    await startServer();
                    if (mainWindow) {
                        mainWindow.reload();
                    }
                    showNotification(APP_NAME, 'تم إعادة تشغيل السيرفر');
                } catch (e) {
                    showNotification(APP_NAME, 'فشل إعادة تشغيل السيرفر');
                }
            },
        },
        { type: 'separator' },
        {
            label: 'خروج',
            click: () => {
                isQuitting = true;
                app.quit();
            },
        },
    ]);

    tray.setToolTip(APP_NAME);
    tray.setContextMenu(contextMenu);

    tray.on('click', () => {
        if (mainWindow) {
            if (mainWindow.isVisible()) {
                mainWindow.focus();
            } else {
                mainWindow.show();
                if (process.platform === 'darwin') {
                    app.dock.show();
                }
            }
        }
    });

    tray.on('double-click', () => {
        if (mainWindow) {
            mainWindow.show();
            mainWindow.focus();
        }
    });
}

// ========== Notifications ==========
function showNotification(title, body) {
    if (!settings.notifications) return;
    if (Notification.isSupported()) {
        new Notification({
            title,
            body,
            icon: getIconPath(),
            silent: false,
        }).show();
    }
}

// ========== IPC Handlers ==========
function setupIPC() {
    ipcMain.handle('get-settings', () => settings);

    ipcMain.handle('save-settings', (event, newSettings) => {
        settings = { ...settings, ...newSettings };
        saveSettings();
        return true;
    });

    ipcMain.handle('show-notification', (event, { title, body }) => {
        showNotification(title, body);
    });

    ipcMain.handle('get-server-url', () => SERVER_URL);

    ipcMain.handle('get-app-version', () => app.getVersion());

    ipcMain.handle('get-app-path', () => app.getPath('userData'));

    ipcMain.handle('show-open-dialog', async (event, options) => {
        return dialog.showOpenDialog(mainWindow, options);
    });

    ipcMain.handle('show-save-dialog', async (event, options) => {
        return dialog.showSaveDialog(mainWindow, options);
    });

    ipcMain.on('flash-frame', () => {
        if (mainWindow && !mainWindow.isFocused()) {
            mainWindow.flashFrame(true);
        }
    });

    ipcMain.on('set-badge', (event, count) => {
        if (process.platform === 'darwin') {
            app.dock.setBadge(count > 0 ? String(count) : '');
        }
    });

    ipcMain.handle('set-auto-start', (event, enable) => {
        setAutoStart(enable);
        return true;
    });

    ipcMain.handle('check-for-updates', () => {
        if (autoUpdater) {
            autoUpdater.checkForUpdates().catch(() => {});
            return true;
        }
        return false;
    });
}

// ========== Icons ==========
function getIconPath() {
    const iconDir = path.join(__dirname, 'icons');
    if (process.platform === 'win32') {
        const ico = path.join(iconDir, 'icon.ico');
        if (fs.existsSync(ico)) return ico;
    }
    const png = path.join(iconDir, 'icon.png');
    if (fs.existsSync(png)) return png;
    return undefined;
}

function getTrayIcon() {
    const iconPath = getIconPath();
    if (iconPath) {
        let img = nativeImage.createFromPath(iconPath);
        if (process.platform === 'darwin') {
            img = img.resize({ width: 22, height: 22 });
        } else {
            img = img.resize({ width: 24, height: 24 });
        }
        return img;
    }
    // Create a simple colored icon if no icon file
    return nativeImage.createFromDataURL(
        'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAACAAAAAgCAYAAABzenr0AAAAAXNSR0IArs4c6QAAALRJREFUWEft1rENwCAMBdDbmQWYhJmYhEmYhVmAHSJFipQCzH9xejjJL2xsKAO/MnB+GgEjwAh4Au/83Drnuf3Z1h1X+4g3AvUEKr67CXSCBHIA9TOoQ6eeAIIqGQF1D9Yq+B6sJpCjYAQYgU8g9xF1CPYJlBOI7YC6h3oJxBZARYAR+ASSPdgroJ3D+QItB+ITiCxAiwAjMBzOj4BPAKgfIH8BIJGoBGIBIyCEfgv8AVmPTUhjgqFKwAAAABJRU5ErkJggg=='
    );
}

// ========== Loading Window ==========
function createLoadingWindow() {
    const loadingWin = new BrowserWindow({
        width: 400,
        height: 300,
        frame: false,
        transparent: true,
        resizable: false,
        center: true,
        webPreferences: {
            nodeIntegration: false,
            contextIsolation: true,
        },
    });

    loadingWin.loadURL(`data:text/html;charset=utf-8,${encodeURIComponent(`
<!DOCTYPE html>
<html dir="rtl">
<head>
<style>
* { margin:0; padding:0; box-sizing:border-box; }
body {
    background: rgba(10,10,26,0.95);
    color: #e0e0e0;
    font-family: 'Segoe UI', Tahoma, sans-serif;
    display: flex;
    align-items: center;
    justify-content: center;
    height: 100vh;
    border-radius: 16px;
    border: 1px solid rgba(0,212,255,0.2);
    -webkit-app-region: drag;
}
.container { text-align: center; }
h1 { color: #00d4ff; font-size: 2em; margin-bottom: 10px; }
p { color: rgba(255,255,255,0.5); font-size: 0.9em; margin-bottom: 30px; }
.spinner {
    width: 40px; height: 40px; margin: 0 auto;
    border: 3px solid rgba(0,212,255,0.2);
    border-top-color: #00d4ff;
    border-radius: 50%;
    animation: spin 1s linear infinite;
}
@keyframes spin { to { transform: rotate(360deg); } }
.status { margin-top: 20px; font-size: 0.8em; color: rgba(255,255,255,0.4); }
</style>
</head>
<body>
<div class="container">
    <h1>هيلين WiFi</h1>
    <p>جاري تشغيل السيرفر...</p>
    <div class="spinner"></div>
    <div class="status">Helen WiFi Desktop v2.0</div>
</div>
</body>
</html>
    `)}`);

    return loadingWin;
}

// ========== App Lifecycle ==========
// Handle deep link on macOS
app.on('open-url', (event, url) => {
    event.preventDefault();
    handleDeepLink(url);
});

function handleDeepLink(url) {
    // Parse bro:// URLs: bro://room/roomname, bro://user/username, bro://call/username
    if (!url || !url.startsWith(PROTOCOL_NAME + '://')) return;
    const path = url.replace(PROTOCOL_NAME + '://', '');
    const [action, target] = path.split('/');
    if (mainWindow) {
        mainWindow.show();
        mainWindow.focus();
        mainWindow.webContents.send('deep-link', { action, target });
    }
}

app.whenReady().then(async () => {
    loadSettings();
    setupIPC();
    // Apply auto-start setting
    if (settings.autoStart) {
        setAutoStart(true);
    }

    const loadingWin = createLoadingWindow();

    try {
        // Check if server is already running
        try {
            await waitForServer(SERVER_PORT, 2000);
            serverReady = true;
            console.log('Server already running');
        } catch {
            // Start the server
            await startServer();
        }

        loadingWin.close();
        createWindow();
        createTray();
        initAutoUpdater();

        // Handle deep link from command line args (Windows/Linux)
        const deepLinkArg = process.argv.find(a => a.startsWith(PROTOCOL_NAME + '://'));
        if (deepLinkArg) {
            setTimeout(() => handleDeepLink(deepLinkArg), 1000);
        }

        // Check if started with --hidden flag (auto-start)
        if (process.argv.includes('--hidden') || settings.startMinimized) {
            if (mainWindow) mainWindow.hide();
        }

    } catch (error) {
        console.error('Failed to start:', error);
        loadingWin.close();

        dialog.showErrorBox(
            'Helen WiFi - خطأ',
            `فشل تشغيل السيرفر\n${error.message}\n\nتأكد من عدم تشغيل نسخة أخرى`
        );
        app.quit();
    }
});

app.on('window-all-closed', () => {
    if (process.platform !== 'darwin') {
        if (!settings.minimizeToTray) {
            isQuitting = true;
            app.quit();
        }
    }
});

app.on('activate', () => {
    if (mainWindow) {
        mainWindow.show();
    } else if (serverReady) {
        createWindow();
    }
});

app.on('before-quit', () => {
    isQuitting = true;
    settings.windowBounds = mainWindow ? mainWindow.getBounds() : settings.windowBounds;
    saveSettings();
    stopServer();
});

// Prevent multiple instances
const gotLock = app.requestSingleInstanceLock();
if (!gotLock) {
    app.quit();
} else {
    app.on('second-instance', (event, commandLine) => {
        if (mainWindow) {
            if (mainWindow.isMinimized()) mainWindow.restore();
            mainWindow.show();
            mainWindow.focus();
            // Handle deep link from second instance
            const deepLink = commandLine.find(arg => arg.startsWith(PROTOCOL_NAME + '://'));
            if (deepLink) {
                handleDeepLink(deepLink);
            }
        }
    });
}
