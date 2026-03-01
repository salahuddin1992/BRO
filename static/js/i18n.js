/**
 * Helen WiFi - Internationalization (i18n) System
 * Supports Arabic (ar) and English (en)
 */
const I18N = {
    _lang: localStorage.getItem('helen_lang') || 'ar',
    _listeners: [],

    get lang() { return this._lang; },

    setLang(lang) {
        if (lang !== 'ar' && lang !== 'en') return;
        this._lang = lang;
        localStorage.setItem('helen_lang', lang);
        document.documentElement.lang = lang;
        document.documentElement.dir = lang === 'ar' ? 'rtl' : 'ltr';
        this.applyAll();
        this._listeners.forEach(fn => fn(lang));
    },

    onLangChange(fn) { this._listeners.push(fn); },

    t(key) {
        const dict = this.translations[this._lang] || this.translations.ar;
        return dict[key] || this.translations.ar[key] || key;
    },

    applyAll() {
        document.querySelectorAll('[data-i18n]').forEach(el => {
            const key = el.getAttribute('data-i18n');
            const val = this.t(key);
            if (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA') {
                el.placeholder = val;
            } else if (el.tagName === 'OPTION') {
                el.textContent = val;
            } else {
                el.textContent = val;
            }
        });
        document.querySelectorAll('[data-i18n-title]').forEach(el => {
            el.title = this.t(el.getAttribute('data-i18n-title'));
        });
        document.querySelectorAll('[data-i18n-placeholder]').forEach(el => {
            el.placeholder = this.t(el.getAttribute('data-i18n-placeholder'));
        });
    },

    translations: {
        // ============ Arabic ============
        ar: {
            // App
            'app_name': 'هيلين WiFi',
            'app_subtitle': 'اتصال داخلي',
            'control_panel': 'لوحة التحكم',

            // Auth
            'login': 'دخول',
            'register': 'تسجيل جديد',
            'username': 'اسم المستخدم',
            'password': 'كلمة المرور',
            'username_password_required': 'الاسم وكلمة المرور مطلوبين',

            // Navigation
            'home': 'الرئيسية',
            'users': 'المستخدمون',
            'rooms': 'الغرف',
            'messages': 'الرسائل',
            'files': 'الملفات',
            'clients': 'العملاء',
            'network': 'الشبكة',
            'mesh': 'Mesh',
            'routers': 'الراوترات',
            'backup': 'النسخ الاحتياطي',
            'recordings': 'التسجيلات',
            'settings': 'الإعدادات',
            'logs': 'السجلات',
            'client': 'العميل',
            'logout': 'خروج',

            // Sidebar
            'my_status': 'حالتي:',
            'online': 'متصل',
            'away': 'بعيد',
            'busy': 'مشغول',
            'offline': 'غير متصل',
            'connected_users': 'المتصلون',

            // Chat
            'type_message': 'اكتب رسالتك...',
            'search_messages': 'بحث في الرسائل...',
            'reply_to': 'رد على: ',
            'general': 'عامة',
            'no_results': 'لا توجد نتائج',
            'search_results': 'نتائج البحث: ',
            'load_older': 'تحميل رسائل أقدم...',
            'loading': 'جاري التحميل...',
            'drag_file_here': 'اسحب الملف هنا لمشاركته',
            'shared_file': 'شارك ملف',
            'file_upload_failed': 'فشل رفع الملف',
            'shared_files': 'ملفات مشتركة',

            // Calls
            'incoming_call': 'مكالمة واردة',
            'video_call': 'مكالمة فيديو',
            'audio_call': 'مكالمة صوتية',
            'select_user': 'اختر مستخدم',
            'calling': 'جاري الاتصال...',
            'connected': 'تم الاتصال',
            'disconnected': 'انقطع الاتصال',
            'call_ended': 'انتهت المكالمة',
            'call_rejected': 'تم رفض المكالمة',
            'device_error': 'فشل الوصول للجهاز: ',
            'left': 'غادر',
            'fullscreen': 'ملء الشاشة',
            'record': 'تسجيل',

            // Screen Share
            'screen_share': 'مشاركة الشاشة',
            'stop_sharing': 'إيقاف المشاركة',
            'select_user_for_screen': 'اختر مستخدم لمشاركة الشاشة',
            'screen_share_cancelled': 'تم إلغاء مشاركة الشاشة',
            'screen_share_started': 'بدأت مشاركة الشاشة',
            'started_screen_share': 'بدأ مشاركة الشاشة',
            'screen_share_stopped': 'توقفت مشاركة الشاشة',

            // Recording
            'recording_started': 'بدأ تسجيل المكالمة',
            'recording_saved': 'تم حفظ التسجيل',
            'recording_failed': 'فشل رفع التسجيل',
            'browser_no_record': 'المتصفح لا يدعم التسجيل',

            // E2E
            'encrypted_message': 'رسالة مشفرة',

            // Profile
            'profile': 'الملف الشخصي',
            'display_name': 'الاسم المعروض',
            'update_name': 'تحديث الاسم',
            'change_password': 'تغيير كلمة المرور',
            'current_password': 'كلمة المرور الحالية',
            'new_password': 'كلمة المرور الجديدة',
            'enter_password': 'أدخل كلمة المرور',
            'password_too_short': 'كلمة المرور قصيرة (4 أحرف على الأقل)',
            'close': 'إغلاق',
            'cancel': 'إلغاء',

            // Settings
            'appearance': 'المظهر',
            'theme': 'الثيم',
            'dark': 'داكن',
            'light': 'فاتح',
            'font_size': 'حجم الخط',
            'medium': 'متوسط',
            'small': 'صغير',
            'large': 'كبير',
            'notifications': 'الإشعارات',
            'notification_sounds': 'أصوات الإشعارات',
            'desktop_notifications': 'إشعارات سطح المكتب',
            'security': 'الأمان',
            'e2e_encryption': 'تشفير E2E (الرسائل الخاصة)',
            'calls': 'المكالمات',
            'auto_record': 'تسجيل المكالمات تلقائياً',
            'language': 'اللغة',

            // Connection
            'connection_lost': 'انقطع الاتصال... جاري إعادة الاتصال',
            'disconnected_reason': 'تم قطع اتصالك',

            // Room
            'new_room': 'غرفة جديدة',
            'room_name': 'اسم الغرفة',
            'description_optional': 'وصف (اختياري)',
            'create': 'إنشاء',
            'browse_rooms': 'تصفح الغرف',
            'no_rooms': 'لا توجد غرف',
            'member': 'عضو',
            'joined': 'منضم',
            'join': 'انضمام',
            'leave': 'مغادرة',
            'room_error': 'خطأ في الغرفة',
            'search': 'بحث',

            // Roles
            'admin': 'مدير',
            'moderator': 'مشرف',
            'user': 'مستخدم',

            // Info panel
            'info': 'معلومات',
            'server': 'السيرفر',
            'server_id': 'المعرف',
            'connection_type': 'الاتصال',
            'fiber': 'فايبر',
            'normal': 'عادي',
            'statistics': 'احصائيات',
            'online_count': 'متصلون',
            'messages_count': 'رسائل',
            'files_count': 'ملفات',

            // Typing
            'typing': 'يكتب...',

            // Reply/Delete
            'reply': 'رد',
            'delete': 'حذف',

            // ====== Admin Page ======
            'registered_users': 'مسجلون',
            'banned_users': 'محظورون',
            'db_size': 'حجم القاعدة',
            'uptime': 'التشغيل',
            'ip_address': 'IP',
            'port': 'المنفذ',
            'recent_clients': 'آخر العملاء',
            'user_col': 'المستخدم',
            'name_col': 'الاسم',
            'role_col': 'الصلاحية',
            'status_col': 'الحالة',
            'last_seen': 'آخر ظهور',
            'registered_at': 'التسجيل',
            'actions': 'إجراءات',
            'interface': 'الواجهة',
            'type': 'النوع',
            'active': 'فعال',

            // Admin user actions
            'ban': 'حظر',
            'unban': 'إلغاء حظر',
            'kick': 'طرد',
            'delete_messages': 'حذف رسائل',
            'reset_password': 'كلمة مرور',
            'banned': 'محظور',
            'confirm_ban': 'حظر {user}؟',
            'confirm_delete_user': 'حذف {user} نهائياً؟ سيتم حذف الحساب وعضويات الغرف.',
            'confirm_delete_messages': 'حذف جميع رسائل {user}؟',
            'user_banned': 'تم حظر {user}',
            'user_unbanned': 'تم إلغاء حظر {user}',
            'user_kicked': 'تم طرد {user}',
            'user_deleted': 'تم حذف {user}',
            'messages_deleted_for': 'تم حذف رسائل {user}',
            'password_set': 'تم تعيين كلمة المرور',

            // Admin rooms
            'room_id': '#',
            'room_description': 'الوصف',
            'creator': 'المنشئ',
            'members': 'الأعضاء',
            'date': 'التاريخ',
            'confirm_delete_room': 'حذف الغرفة؟ سيتم حذف جميع الرسائل فيها.',
            'room_deleted': 'تم حذف الغرفة',
            'no_rooms_exist': 'لا توجد غرف',

            // Admin messages
            'msg_id': 'المعرف',
            'sender': 'المرسل',
            'message': 'الرسالة',
            'room': 'الغرفة',
            'time': 'الوقت',
            'message_deleted': 'تم حذف الرسالة',
            'no_messages': 'لا توجد رسائل',
            'no_results_found': 'لا توجد نتائج',

            // Admin files
            'file': 'الملف',
            'size': 'الحجم',
            'uploader': 'الرافع',
            'download': 'تحميل',
            'confirm_delete_file': 'حذف الملف؟',
            'file_deleted': 'تم حذف الملف',
            'no_files': 'لا توجد ملفات',

            // Admin clients
            'connected_clients': 'العملاء المتصلون',
            'sid': 'المعرف',

            // Admin network
            'network_interfaces': 'واجهات الشبكة',
            'netmask': 'Netmask',

            // Admin mesh
            'mesh_network': 'شبكة Mesh',
            'server_ip': 'IP الخادم',
            'connect': 'اتصال',
            'remote_users': 'المستخدمون البعيدون',
            'no_servers': 'لا توجد خوادم',
            'no_remote_users': 'لا يوجد مستخدمون بعيدون',
            'connecting_to': 'جاري الاتصال بـ {host}',

            // Admin routers
            'supported_routers': 'الراوترات والكوابل المدعومة',
            'works_all_routers': 'يعمل على جميع أنواع الراوترات',

            // Admin backup
            'create_backup': 'إنشاء نسخة احتياطية',
            'backup_description': 'وصف النسخة الاحتياطية',
            'restore_backup': 'استعادة نسخة احتياطية',
            'restore_warning': 'تحذير: سيتم استبدال البيانات الحالية بالنسخة المختارة',
            'restore': 'استعادة',
            'backup_created': 'تم إنشاء النسخة الاحتياطية',
            'confirm_restore': 'استعادة النسخة الاحتياطية؟ سيتم استبدال جميع البيانات الحالية!',
            'confirm_restore_2': 'هل أنت متأكد؟ هذا الإجراء لا يمكن التراجع عنه.',
            'backup_restored': 'تم استعادة النسخة الاحتياطية. يرجى إعادة تحميل الصفحة.',
            'restore_failed': 'فشل الاستعادة',
            'confirm_delete_backup': 'حذف النسخة الاحتياطية؟',
            'backup_deleted': 'تم حذف النسخة',
            'no_backups': 'لا توجد نسخ احتياطية',

            // Admin recordings
            'call_recordings': 'تسجيلات المكالمات',
            'caller': 'المتصل',
            'callee': 'المتلقي',
            'duration': 'المدة',
            'video': 'فيديو',
            'audio': 'صوت',
            'confirm_delete_recording': 'حذف التسجيل؟',
            'recording_deleted': 'تم حذف التسجيل',
            'no_recordings': 'لا توجد تسجيلات',

            // Admin settings
            'change_admin_password': 'تغيير كلمة مرور الأدمن',
            'confirm_password': 'تأكيد كلمة المرور',
            'change': 'تغيير',
            'password_mismatch': 'كلمة المرور غير متطابقة',
            'password_changed': 'تم تغيير كلمة المرور',

            // Admin reset password modal
            'reset_password_title': 'إعادة تعيين كلمة المرور',
            'set': 'تعيين',

            // Admin role
            'role_set': 'تم تعيين صلاحية {user} إلى {role}',

            // Server stopped
            'server_stopped': 'توقف السيرفر بشكل غير متوقع',

            // Electron loading
            'loading_server': 'جاري تشغيل السيرفر...',

            // Tray menu
            'tray_open': 'فتح Helen WiFi',
            'tray_admin': 'لوحة التحكم',
            'tray_notifications': 'الإشعارات',
            'tray_minimize': 'تصغير لشريط المهام',
            'tray_restart': 'إعادة تشغيل السيرفر',
            'tray_quit': 'خروج',
            'tray_restart_ok': 'تم إعادة تشغيل السيرفر',
            'tray_restart_fail': 'فشل إعادة تشغيل السيرفر',
            'tray_error_title': 'Helen WiFi - خطأ',
            'tray_error_body': 'فشل تشغيل السيرفر',
            'tray_error_hint': 'تأكد من عدم تشغيل نسخة أخرى',

            // No users
            'no_users': 'لا يوجد مستخدمون',
        },

        // ============ English ============
        en: {
            // App
            'app_name': 'Helen WiFi',
            'app_subtitle': 'Internal Communication',
            'control_panel': 'Control Panel',

            // Auth
            'login': 'Login',
            'register': 'Register',
            'username': 'Username',
            'password': 'Password',
            'username_password_required': 'Username and password are required',

            // Navigation
            'home': 'Dashboard',
            'users': 'Users',
            'rooms': 'Rooms',
            'messages': 'Messages',
            'files': 'Files',
            'clients': 'Clients',
            'network': 'Network',
            'mesh': 'Mesh',
            'routers': 'Routers',
            'backup': 'Backup',
            'recordings': 'Recordings',
            'settings': 'Settings',
            'logs': 'Logs',
            'client': 'Client',
            'logout': 'Logout',

            // Sidebar
            'my_status': 'My status:',
            'online': 'Online',
            'away': 'Away',
            'busy': 'Busy',
            'offline': 'Offline',
            'connected_users': 'Users',

            // Chat
            'type_message': 'Type your message...',
            'search_messages': 'Search messages...',
            'reply_to': 'Reply to: ',
            'general': 'General',
            'no_results': 'No results',
            'search_results': 'Search results: ',
            'load_older': 'Load older messages...',
            'loading': 'Loading...',
            'drag_file_here': 'Drop file here to share',
            'shared_file': 'shared a file',
            'file_upload_failed': 'File upload failed',
            'shared_files': 'Shared Files',

            // Calls
            'incoming_call': 'Incoming Call',
            'video_call': 'Video Call',
            'audio_call': 'Audio Call',
            'select_user': 'Select a user',
            'calling': 'Calling...',
            'connected': 'Connected',
            'disconnected': 'Disconnected',
            'call_ended': 'Call ended',
            'call_rejected': 'Call rejected',
            'device_error': 'Device access failed: ',
            'left': 'left',
            'fullscreen': 'Fullscreen',
            'record': 'Record',

            // Screen Share
            'screen_share': 'Screen Share',
            'stop_sharing': 'Stop Sharing',
            'select_user_for_screen': 'Select a user to share screen',
            'screen_share_cancelled': 'Screen share cancelled',
            'screen_share_started': 'Screen sharing started',
            'started_screen_share': 'started screen sharing',
            'screen_share_stopped': 'Screen sharing stopped',

            // Recording
            'recording_started': 'Call recording started',
            'recording_saved': 'Recording saved',
            'recording_failed': 'Recording upload failed',
            'browser_no_record': 'Browser does not support recording',

            // E2E
            'encrypted_message': '[Encrypted message]',

            // Profile
            'profile': 'Profile',
            'display_name': 'Display Name',
            'update_name': 'Update Name',
            'change_password': 'Change Password',
            'current_password': 'Current Password',
            'new_password': 'New Password',
            'enter_password': 'Enter password',
            'password_too_short': 'Password too short (minimum 4 characters)',
            'close': 'Close',
            'cancel': 'Cancel',

            // Settings
            'appearance': 'Appearance',
            'theme': 'Theme',
            'dark': 'Dark',
            'light': 'Light',
            'font_size': 'Font Size',
            'medium': 'Medium',
            'small': 'Small',
            'large': 'Large',
            'notifications': 'Notifications',
            'notification_sounds': 'Notification Sounds',
            'desktop_notifications': 'Desktop Notifications',
            'security': 'Security',
            'e2e_encryption': 'E2E Encryption (Private Messages)',
            'calls': 'Calls',
            'auto_record': 'Auto-record Calls',
            'language': 'Language',

            // Connection
            'connection_lost': 'Connection lost... Reconnecting',
            'disconnected_reason': 'You have been disconnected',

            // Room
            'new_room': 'New Room',
            'room_name': 'Room Name',
            'description_optional': 'Description (optional)',
            'create': 'Create',
            'browse_rooms': 'Browse Rooms',
            'no_rooms': 'No rooms',
            'member': 'member',
            'joined': 'Joined',
            'join': 'Join',
            'leave': 'Leave',
            'room_error': 'Room error',
            'search': 'Search',

            // Roles
            'admin': 'Admin',
            'moderator': 'Moderator',
            'user': 'User',

            // Info panel
            'info': 'Info',
            'server': 'Server',
            'server_id': 'ID',
            'connection_type': 'Connection',
            'fiber': 'Fiber',
            'normal': 'Standard',
            'statistics': 'Statistics',
            'online_count': 'Online',
            'messages_count': 'Messages',
            'files_count': 'Files',

            // Typing
            'typing': 'is typing...',

            // Reply/Delete
            'reply': 'Reply',
            'delete': 'Delete',

            // ====== Admin Page ======
            'registered_users': 'Registered',
            'banned_users': 'Banned',
            'db_size': 'DB Size',
            'uptime': 'Uptime',
            'ip_address': 'IP',
            'port': 'Port',
            'recent_clients': 'Recent Clients',
            'user_col': 'User',
            'name_col': 'Name',
            'role_col': 'Role',
            'status_col': 'Status',
            'last_seen': 'Last Seen',
            'registered_at': 'Registered',
            'actions': 'Actions',
            'interface': 'Interface',
            'type': 'Type',
            'active': 'Active',

            // Admin user actions
            'ban': 'Ban',
            'unban': 'Unban',
            'kick': 'Kick',
            'delete_messages': 'Delete Messages',
            'reset_password': 'Password',
            'banned': 'Banned',
            'confirm_ban': 'Ban {user}?',
            'confirm_delete_user': 'Permanently delete {user}? Account and room memberships will be deleted.',
            'confirm_delete_messages': 'Delete all messages by {user}?',
            'user_banned': '{user} banned',
            'user_unbanned': '{user} unbanned',
            'user_kicked': '{user} kicked',
            'user_deleted': '{user} deleted',
            'messages_deleted_for': 'Messages by {user} deleted',
            'password_set': 'Password set',

            // Admin rooms
            'room_id': '#',
            'room_description': 'Description',
            'creator': 'Creator',
            'members': 'Members',
            'date': 'Date',
            'confirm_delete_room': 'Delete room? All messages in it will be deleted.',
            'room_deleted': 'Room deleted',
            'no_rooms_exist': 'No rooms',

            // Admin messages
            'msg_id': 'ID',
            'sender': 'Sender',
            'message': 'Message',
            'room': 'Room',
            'time': 'Time',
            'message_deleted': 'Message deleted',
            'no_messages': 'No messages',
            'no_results_found': 'No results found',

            // Admin files
            'file': 'File',
            'size': 'Size',
            'uploader': 'Uploader',
            'download': 'Download',
            'confirm_delete_file': 'Delete file?',
            'file_deleted': 'File deleted',
            'no_files': 'No files',

            // Admin clients
            'connected_clients': 'Connected Clients',
            'sid': 'SID',

            // Admin network
            'network_interfaces': 'Network Interfaces',
            'netmask': 'Netmask',

            // Admin mesh
            'mesh_network': 'Mesh Network',
            'server_ip': 'Server IP',
            'connect': 'Connect',
            'remote_users': 'Remote Users',
            'no_servers': 'No servers',
            'no_remote_users': 'No remote users',
            'connecting_to': 'Connecting to {host}',

            // Admin routers
            'supported_routers': 'Supported Routers & Cables',
            'works_all_routers': 'Works with all router types',

            // Admin backup
            'create_backup': 'Create Backup',
            'backup_description': 'Backup description',
            'restore_backup': 'Restore Backup',
            'restore_warning': 'Warning: Current data will be replaced with the selected backup',
            'restore': 'Restore',
            'backup_created': 'Backup created',
            'confirm_restore': 'Restore backup? All current data will be replaced!',
            'confirm_restore_2': 'Are you sure? This action cannot be undone.',
            'backup_restored': 'Backup restored. Please reload the page.',
            'restore_failed': 'Restore failed',
            'confirm_delete_backup': 'Delete backup?',
            'backup_deleted': 'Backup deleted',
            'no_backups': 'No backups',

            // Admin recordings
            'call_recordings': 'Call Recordings',
            'caller': 'Caller',
            'callee': 'Callee',
            'duration': 'Duration',
            'video': 'Video',
            'audio': 'Audio',
            'confirm_delete_recording': 'Delete recording?',
            'recording_deleted': 'Recording deleted',
            'no_recordings': 'No recordings',

            // Admin settings
            'change_admin_password': 'Change Admin Password',
            'confirm_password': 'Confirm Password',
            'change': 'Change',
            'password_mismatch': 'Passwords do not match',
            'password_changed': 'Password changed',

            // Admin reset password modal
            'reset_password_title': 'Reset Password',
            'set': 'Set',

            // Admin role
            'role_set': '{user} role set to {role}',

            // Server stopped
            'server_stopped': 'Server stopped unexpectedly',

            // Electron loading
            'loading_server': 'Starting server...',

            // Tray menu
            'tray_open': 'Open Helen WiFi',
            'tray_admin': 'Control Panel',
            'tray_notifications': 'Notifications',
            'tray_minimize': 'Minimize to Tray',
            'tray_restart': 'Restart Server',
            'tray_quit': 'Quit',
            'tray_restart_ok': 'Server restarted',
            'tray_restart_fail': 'Server restart failed',
            'tray_error_title': 'Helen WiFi - Error',
            'tray_error_body': 'Server startup failed',
            'tray_error_hint': 'Make sure another instance is not running',

            // No users
            'no_users': 'No users',
        }
    }
};

// Shortcut function
function t(key) { return I18N.t(key); }
