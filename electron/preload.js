/**
 * Helen WiFi - Electron Preload Script
 * Secure bridge between renderer process and main process
 */
const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('helenDesktop', {
    // Settings
    getSettings: () => ipcRenderer.invoke('get-settings'),
    saveSettings: (settings) => ipcRenderer.invoke('save-settings', settings),

    // Notifications
    showNotification: (title, body) => ipcRenderer.invoke('show-notification', { title, body }),

    // Window
    flashFrame: () => ipcRenderer.send('flash-frame'),
    setBadge: (count) => ipcRenderer.send('set-badge', count),

    // App info
    getServerUrl: () => ipcRenderer.invoke('get-server-url'),
    getVersion: () => ipcRenderer.invoke('get-app-version'),
    getAppPath: () => ipcRenderer.invoke('get-app-path'),

    // Dialogs
    showOpenDialog: (options) => ipcRenderer.invoke('show-open-dialog', options),
    showSaveDialog: (options) => ipcRenderer.invoke('show-save-dialog', options),

    // Platform
    platform: process.platform,
    isElectron: true,
});
