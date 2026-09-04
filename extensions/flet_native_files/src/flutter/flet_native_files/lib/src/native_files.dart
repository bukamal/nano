import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:cross_file/cross_file.dart';
import 'package:file_picker/file_picker.dart';
import 'package:flet/flet.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_local_notifications/flutter_local_notifications.dart';
import 'package:mobile_scanner/mobile_scanner.dart';
import 'package:path_provider/path_provider.dart';
import 'package:pdf/pdf.dart';
import 'package:printing/printing.dart';
import 'package:share_plus/share_plus.dart';
// hide Row: sqlite3 exports its own `Row` (a SQL result row) which
// collides with Flutter's `Row` widget the moment either file in this
// package actually uses the widget by that bare name -- as
// _BarcodeScanPageState._buildHintPill now does. Nothing here references
// sqlite3's Row type directly (result sets are walked with `for (final row
// in resultSet)`, never typed as `Row` explicitly), so hiding it is safe
// and keeps `Row` meaning the widget everywhere in this file.
import 'package:sqlite3/sqlite3.dart' hide Row;
import 'package:workmanager/workmanager.dart';

import 'sound_pool.dart';

// -- Closed-app smart notifications ----------------------------------------
//
// Everything below this comment (down to FletNativeFilesControl) supports
// PHASE9's second half: alerts while the app itself is not running.
// notification_service.py's rules engine only exists while Python is alive,
// so it cannot fire anything once the app is closed. The approach here is
// deliberately *not* to reimplement that whole engine natively -- instead:
//
//   1. Python still owns every rule/threshold (see NotificationService
//      .native_schedule_payload in notification_service.py) and hands this
//      side a plain JSON config plus the exact on-disk path to the same
//      SQLite database the app itself uses (core/paths.database_path()).
//   2. A WorkManager periodic task (Android-only; iOS/web silently no-op --
//      see the try/catch in ensureInitialized) wakes a *separate* background
//      isolate every few hours, opens that same .db file directly (SQLite's
//      own file locking makes this safe even if the app happens to be open
//      at the same moment) and re-runs simplified versions of four checks:
//      receivables, low stock, backup age, license expiry.
//   3. Matches are deduped through the *same* notification_log table Python
//      writes to (same dedupe_key convention: '<rule>:<yyyy-mm-dd>'), so a
//      condition the app already surfaced today never double-fires here,
//      and anything this isolate raises shows up in-app too next time the
//      user opens the bell panel.
//
// This intentionally does not cover the "ملخص ذكي" (sales-drop insight)
// rule -- that one compares against a rolling 7-day average computed by
// ReportingService/DashboardService, and reimplementing that aggregation
// natively risked disagreeing with what the in-app dashboard shows for the
// same day. It stays an in-app-only alert.

const String kNotifyTaskName = 'nano_notification_check';
const String kNotifyUniqueName = 'nano_notification_check_periodic';
const String kNotifyChannelId = 'nano_alerts';
const String kNotifyChannelName = 'تنبيهات نانو';
const String kNotifyChannelDescription =
    'تنبيهات ذكية للذمم المتأخرة والمخزون المنخفض والنسخ الاحتياطي والترخيص';

// One-off (not periodic) task used by the "close the app and wait" delayed
// test button in notifications_view.py -- see schedule_test_notification
// below. Unlike kNotifyTaskName's periodic schedule, WorkManager does not
// clamp a one-off task's initialDelay to 15 minutes, so this can genuinely
// verify short delays (seconds to a few minutes) fire while the app is
// fully closed, not just while it's foregrounded like send_test_notification.
const String kTestNotifyTaskName = 'nano_test_notification_delayed';
const String kTestNotifyUniqueName = 'nano_test_notification_delayed_once';

final FlutterLocalNotificationsPlugin _localNotifications = FlutterLocalNotificationsPlugin();
bool _localNotificationsReady = false;

Future<void> _ensureLocalNotificationsInitialized() async {
  if (_localNotificationsReady) return;
  const androidInit = AndroidInitializationSettings('@mipmap/ic_launcher');
  await _localNotifications.initialize(const InitializationSettings(android: androidInit));
  const channel = AndroidNotificationChannel(
    kNotifyChannelId,
    kNotifyChannelName,
    description: kNotifyChannelDescription,
    importance: Importance.high,
  );
  await _localNotifications
      .resolvePlatformSpecificImplementation<AndroidFlutterLocalNotificationsPlugin>()
      ?.createNotificationChannel(channel);
  _localNotificationsReady = true;
}

/// Fires one real Android local notification through the shared
/// kNotifyChannelId/_localNotifications plugin instance. Shared by the
/// immediate 'send_test_notification' handler (fires right away, while the
/// app is still foregrounded) and the delayed one-off WorkManager task
/// below (fires later, typically after the app has been closed) -- same
/// notification, two different triggers, so a person can compare them.
Future<void> _showLocalTestNotification({required String title, required String body}) async {
  await _ensureLocalNotificationsInitialized();
  await _localNotifications.show(
    // Fixed, recognizable id so a second test replaces the first instead
    // of stacking duplicates.
    990001,
    title.isEmpty ? 'إشعار اختبار' : title,
    body.isEmpty ? 'وصل هذا الإشعار بنجاح -- نظام التنبيهات يعمل.' : body,
    const NotificationDetails(
      android: AndroidNotificationDetails(
        kNotifyChannelId,
        kNotifyChannelName,
        channelDescription: kNotifyChannelDescription,
        importance: Importance.high,
        priority: Priority.high,
      ),
    ),
  );
}

/// Entry point for the background isolate WorkManager spins up. Must stay
/// top-level (or static) and keep the `vm:entry-point` annotation, or a
/// release build's tree-shaker can strip it and the periodic task silently
/// never fires -- it won't error, it just won't run.
@pragma('vm:entry-point')
void notificationCallbackDispatcher() {
  Workmanager().executeTask((task, inputData) async {
    try {
      final data = inputData ?? const <String, dynamic>{};
      if (task == kTestNotifyTaskName) {
        // The delayed "close the app and wait" test -- see
        // schedule_test_notification in handleMethod below.
        await _showLocalTestNotification(
          title: (data['title'] as String?) ?? '',
          body: (data['body'] as String?) ?? '',
        );
      } else {
        await _runNotificationCheck(data);
      }
    } catch (error) {
      // A background isolate has nowhere to surface this to a person, and
      // WorkManager will retry the next periodic run regardless -- so this
      // is purely for anyone reading device logs, not user-facing.
      debugPrint('nano background notification check failed: $error');
    }
    return Future.value(true);
  });
}

bool _inQuietHours(Map<String, dynamic> config) {
  final quiet = (config['quiet_hours'] as Map?) ?? const {};
  if (quiet['enabled'] != true) return false;
  final start = (quiet['start_hour'] as num?)?.toInt() ?? 22;
  final end = (quiet['end_hour'] as num?)?.toInt() ?? 8;
  if (start == end) return false;
  final hour = DateTime.now().hour;
  return start < end ? (hour >= start && hour < end) : (hour >= start || hour < end);
}

class _NativeAlert {
  final String ruleKey;
  final String dedupeKey;
  final String severity;
  final String title;
  final String body;

  _NativeAlert({
    required this.ruleKey,
    required this.dedupeKey,
    required this.severity,
    required this.title,
    required this.body,
  });
}

String _todayKey() => DateTime.now().toIso8601String().substring(0, 10);

List<_NativeAlert> _checkReceivables(Database db, Map<String, dynamic> config) {
  final cfg = (config['receivables'] as Map?) ?? const {};
  if (cfg['enabled'] != true) return const [];
  final overdueAfterDays = (cfg['overdue_after_days'] as num?)?.toInt() ?? 30;
  final now = DateTime.now();
  final rows = db.select(
    "SELECT invoice_date, (total - paid_amount) AS balance FROM invoices "
    "WHERE type = 'sale' AND status != 'cancelled' AND (total - paid_amount) > 0.01",
  );
  var overdueCount = 0;
  var overdueTotal = 0.0;
  for (final row in rows) {
    final dateStr = row['invoice_date'] as String?;
    if (dateStr == null) continue;
    final invoiceDate = DateTime.tryParse(dateStr);
    if (invoiceDate == null) continue;
    if (now.difference(invoiceDate).inDays >= overdueAfterDays) {
      overdueCount++;
      overdueTotal += (row['balance'] as num?)?.toDouble() ?? 0;
    }
  }
  if (overdueCount == 0) return const [];
  return [
    _NativeAlert(
      ruleKey: 'receivables',
      dedupeKey: 'receivables:${_todayKey()}',
      severity: 'warning',
      title: 'ذمم متأخرة',
      body: 'لديك $overdueCount فاتورة بيع متأخرة السداد بإجمالي ${overdueTotal.toStringAsFixed(0)}',
    ),
  ];
}

List<_NativeAlert> _checkLowStock(Database db, Map<String, dynamic> config) {
  final cfg = (config['low_stock'] as Map?) ?? const {};
  if (cfg['enabled'] != true) return const [];
  final threshold = (cfg['default_threshold'] as num?)?.toDouble() ?? 5;
  final rows = db.select(
    "SELECT COUNT(*) AS c FROM items WHERE item_type = 'مخزون' AND quantity <= ?",
    [threshold],
  );
  final count = (rows.isEmpty ? 0 : rows.first['c'] as num?)?.toInt() ?? 0;
  if (count == 0) return const [];
  return [
    _NativeAlert(
      ruleKey: 'low_stock',
      dedupeKey: 'low_stock:${_todayKey()}',
      severity: 'warning',
      title: 'مخزون منخفض',
      body: 'لديك $count صنف وصل إلى الحد الأدنى من الكمية',
    ),
  ];
}

List<_NativeAlert> _checkBackup(Database db, Map<String, dynamic> config) {
  final cfg = (config['backup'] as Map?) ?? const {};
  if (cfg['enabled'] != true) return const [];
  final remindAfterDays = (cfg['remind_after_days'] as num?)?.toInt() ?? 7;
  final rows = db.select("SELECT value FROM settings WHERE key = 'last_backup_at'");
  // No recorded backup yet (brand-new install) -- the in-app dashboard
  // already nudges a first-time user toward backing up; no need to also
  // wake their phone about it before they've even opened Nano once.
  if (rows.isEmpty) return const [];
  final lastBackup = DateTime.tryParse(rows.first['value'] as String? ?? '');
  if (lastBackup == null) return const [];
  final ageDays = DateTime.now().difference(lastBackup).inDays;
  if (ageDays < remindAfterDays) return const [];
  return [
    _NativeAlert(
      ruleKey: 'backup',
      dedupeKey: 'backup:${_todayKey()}',
      severity: 'warning',
      title: 'تذكير بالنسخ الاحتياطي',
      body: 'مرّ أكثر من $ageDays يومًا منذ آخر نسخة احتياطية',
    ),
  ];
}

List<_NativeAlert> _checkLicense(Database db, Map<String, dynamic> config) {
  final cfg = (config['license'] as Map?) ?? const {};
  if (cfg['enabled'] != true) return const [];
  final remindBeforeDays = (cfg['remind_before_days'] as num?)?.toInt() ?? 14;
  final rows = db.select('SELECT expires_at FROM license_state WHERE id = 1');
  if (rows.isEmpty || rows.first['expires_at'] == null) return const [];
  final expires = DateTime.tryParse(rows.first['expires_at'] as String);
  if (expires == null) return const [];
  final daysLeft = expires.difference(DateTime.now()).inDays;
  if (daysLeft > remindBeforeDays) return const [];
  return [
    _NativeAlert(
      ruleKey: 'license',
      dedupeKey: 'license:${_todayKey()}',
      severity: 'urgent',
      title: 'الترخيص',
      body: daysLeft < 0 ? 'انتهت صلاحية الترخيص' : 'تنتهي صلاحية الترخيص خلال $daysLeft يومًا',
    ),
  ];
}

// -- PHASE10: home screen widget (Glance) -----------------------------------
//
// One shared sink for both update paths described in
// PHASE10_HOME_WIDGET_GLANCE_AR.md:
//   1. Immediate: 'push_home_widget' case above, called from Python right
//      after a sale/receipt/payment posts while the app is open.
//   2. Periodic fallback: _pushHomeWidgetSnapshot below, called from inside
//      _runNotificationCheck's already-open `db` connection -- the same
//      WorkManager isolate PHASE9 already uses for closed-app alerts, so
//      this adds zero new background wake-ups or SQLite opens.
// Both funnel into the same native channel; NanoHomeWidgetPlugin.kt is the
// single place that actually touches the Glance widget state.
const MethodChannel _homeWidgetChannel = MethodChannel('nano/home_widget');

Future<void> _pushHomeWidgetJson(String snapshotJson) async {
  try {
    await _homeWidgetChannel.invokeMethod('push', snapshotJson);
  } catch (error) {
    // Widgets are a nice-to-have surface, not a critical path -- a device
    // without the Glance widget dependencies (or a non-Android platform)
    // must never take down the sale/notification flow that called this.
    debugPrint('nano home widget push failed: $error');
  }
}

Future<void> _pushHomeWidgetSnapshot(Database db) async {
  final sales = db.select(
    "SELECT COALESCE(SUM(total),0) s FROM invoices "
    "WHERE type = 'sale' AND status != 'cancelled' AND date(invoice_date) = date('now','localtime')",
  ).first['s'] as num? ?? 0;
  // Same definition DashboardService.summary() uses on the Python side
  // (sum of debit-credit on the CASH ledger account) -- there is no
  // separate cash_transactions table in this schema.
  final cash = db.select(
    "SELECT COALESCE(SUM(debit-credit),0) c FROM ledger_entries WHERE account_code = 'CASH'",
  ).first['c'] as num? ?? 0;
  final overdue = db.select(
    "SELECT COUNT(*) c FROM invoices WHERE type = 'sale' AND status != 'cancelled' AND (total - paid_amount) > 0.01",
  ).first['c'] as num? ?? 0;
  final lowStock = db.select(
    "SELECT COUNT(*) c FROM items WHERE item_type = 'مخزون' AND quantity <= 5",
  ).first['c'] as num? ?? 0;

  await _pushHomeWidgetJson(jsonEncode({
    'sales_today': sales,
    'cash_balance': cash,
    'overdue_count': overdue,
    'low_stock_count': lowStock,
    'updated_at': DateTime.now().toIso8601String(),
  }));
}

Future<void> _runNotificationCheck(Map<String, dynamic> inputData) async {
  final dbPath = (inputData['db_path'] as String?) ?? '';
  if (dbPath.isEmpty || !await File(dbPath).exists()) return;

  Map<String, dynamic> config;
  try {
    config = jsonDecode((inputData['config_json'] as String?) ?? '{}') as Map<String, dynamic>;
  } catch (_) {
    config = const {};
  }
  if (_inQuietHours(config)) return;

  final alerts = <_NativeAlert>[];
  final db = sqlite3.open(dbPath, mode: OpenMode.readWrite);
  try {
    db.execute('PRAGMA busy_timeout = 3000;');
    alerts.addAll(_checkReceivables(db, config));
    alerts.addAll(_checkLowStock(db, config));
    alerts.addAll(_checkBackup(db, config));
    alerts.addAll(_checkLicense(db, config));

    // PHASE10: refresh the home screen widget every periodic pass regardless
    // of whether any alert fired -- sales/cash numbers change even on a
    // perfectly healthy day with zero alerts, and this is the only path
    // that can refresh them while the app is fully closed.
    await _pushHomeWidgetSnapshot(db);

    if (alerts.isEmpty) return;

    await _ensureLocalNotificationsInitialized();
    var notifyId = DateTime.now().millisecondsSinceEpoch.remainder(1 << 31);
    for (final alert in alerts) {
      final already = db.select(
        'SELECT 1 FROM notification_log WHERE dedupe_key = ?',
        [alert.dedupeKey],
      );
      if (already.isNotEmpty) continue;

      db.execute(
        'INSERT OR IGNORE INTO notification_log (dedupe_key, rule_key, severity, title, body) '
        'VALUES (?, ?, ?, ?, ?)',
        [alert.dedupeKey, alert.ruleKey, alert.severity, alert.title, alert.body],
      );
      await _localNotifications.show(
        notifyId++,
        alert.title,
        alert.body,
        const NotificationDetails(
          android: AndroidNotificationDetails(
            kNotifyChannelId,
            kNotifyChannelName,
            channelDescription: kNotifyChannelDescription,
            importance: Importance.high,
            priority: Priority.high,
          ),
        ),
      );
    }
  } finally {
    db.dispose();
  }
}

class FletNativeFilesControl extends StatefulWidget {
  final Control? parent;
  final Control control;
  final List<Control> children;
  final FletControlBackend backend;

  const FletNativeFilesControl({
    super.key,
    required this.parent,
    required this.control,
    required this.children,
    required this.backend,
  });

  @override
  State<FletNativeFilesControl> createState() => _FletNativeFilesControlState();
}

class _FletNativeFilesControlState extends State<FletNativeFilesControl> {
  @override
  void initState() {
    super.initState();
    widget.backend.subscribeMethods(widget.control.id, handleMethod);
  }

  List<String> parseExtensions(String? raw) {
    if (raw == null || raw.isEmpty) return const [];
    try {
      return (jsonDecode(raw) as List<dynamic>)
          .map((x) => x.toString().replaceAll('.', '').toLowerCase())
          .where((x) => x.isNotEmpty)
          .toList();
    } catch (_) {
      return const [];
    }
  }

  Future<String?> materializePickedFile(PlatformFile file) async {
    if (file.path != null && file.path!.isNotEmpty) return file.path!;
    if (file.bytes == null) return null;
    final dir = await getTemporaryDirectory();
    final safeName = file.name.replaceAll(RegExp(r'[^A-Za-z0-9._\-\u0600-\u06FF]'), '_');
    final out = File('${dir.path}/nano_import_${DateTime.now().millisecondsSinceEpoch}_$safeName');
    await out.writeAsBytes(file.bytes!, flush: true);
    return out.path;
  }

  Future<File> createPdfFile(String html, String requestedName) async {
    if (html.isEmpty) {
      throw Exception('محتوى التقرير فارغ');
    }
    final bytes = await Printing.convertHtml(format: PdfPageFormat.a4, html: html);
    final dir = await getTemporaryDirectory();
    var safeName = requestedName.trim().isEmpty ? 'nano-report.pdf' : requestedName.trim();
    if (!safeName.toLowerCase().endsWith('.pdf')) safeName = '$safeName.pdf';
    safeName = safeName.replaceAll(RegExp(r'[^A-Za-z0-9._\-\u0600-\u06FF]'), '_');
    final out = File('${dir.path}/nano_pdf_${DateTime.now().millisecondsSinceEpoch}_$safeName');
    await out.writeAsBytes(bytes, flush: true);
    if (!await out.exists() || await out.length() == 0) {
      throw Exception('تعذر إنشاء ملف PDF');
    }
    return out;
  }

  Future<String?> handleMethod(String method, Map<String, String> args) async {
    try {
      switch (method) {
        case 'pick_file':
          final extensions = parseExtensions(args['extensions']);
          final result = await FilePicker.platform.pickFiles(
            allowMultiple: false,
            withData: true,
            dialogTitle: args['dialog_title'],
            type: extensions.isEmpty ? FileType.any : FileType.custom,
            allowedExtensions: extensions.isEmpty ? null : extensions,
          );
          if (result == null || result.files.isEmpty) return 'cancelled';
          final file = result.files.single;
          final path = await materializePickedFile(file);
          if (path == null) return 'error:تعذر الوصول إلى الملف المحدد';
          return jsonEncode({
            'path': path,
            'name': file.name,
            'size': file.size,
            'extension': file.extension,
          });

        case 'share_file':
          final path = args['path'] ?? '';
          if (path.isEmpty || !await File(path).exists()) return 'error:الملف غير موجود';
          final result = await Share.shareXFiles(
            [XFile(path, mimeType: args['mime_type'])],
            text: (args['text'] ?? '').isEmpty ? null : args['text'],
            subject: (args['subject'] ?? '').isEmpty ? null : args['subject'],
          );
          return result.status == ShareResultStatus.dismissed ? 'cancelled' : 'ok';

        case 'print_html':
          final html = args['html'] ?? '';
          if (html.isEmpty) return 'error:محتوى التقرير فارغ';
          await Printing.layoutPdf(
            name: (args['name'] ?? 'nano-report').isEmpty ? 'nano-report' : args['name']!,
            onLayout: (PdfPageFormat format) => Printing.convertHtml(format: format, html: html),
          );
          return 'ok';

        case 'create_pdf':
          final file = await createPdfFile(args['html'] ?? '', args['filename'] ?? 'nano-report.pdf');
          return file.path;

        case 'scan_barcode':
          if (!mounted) return 'error:الواجهة غير جاهزة';
          // Continuous stocktake mode calls scan_barcode() again the
          // instant the previous call returns a code (see
          // stocktake_view.py's scan_loop). _onDetect above now awaits
          // controller.stop() before popping, but a short extra settle
          // delay here too costs nothing on a human-timed scan-to-scan
          // gap and adds margin against the camera black-screen/freeze
          // some Android camera stacks show when a new camera session is
          // requested immediately after the previous one released.
          await Future.delayed(const Duration(milliseconds: 250));
          final code = await Navigator.of(context, rootNavigator: true).push<String?>(
            MaterialPageRoute(builder: (_) => const _BarcodeScanPage(), fullscreenDialog: true),
          );
          if (code == null || code.isEmpty) return 'cancelled';
          return code;

        case 'schedule_notifications':
          final dbPath = args['db_path'] ?? '';
          if (dbPath.isEmpty) return 'error:مسار قاعدة البيانات مفقود';
          if (!Platform.isAndroid) return 'ok'; // no-op on iOS/desktop/web for now
          final requestedMinutes = int.tryParse(args['interval_minutes'] ?? '') ?? 360;
          // WorkManager silently clamps periodic tasks below 15 minutes on
          // Android anyway; clamping here too so the returned 'ok' is honest
          // about what was actually scheduled.
          final minutes = requestedMinutes < 15 ? 15 : requestedMinutes;
          // Anchors the first check near the admin's chosen daily-check
          // hour (see NotificationService._minutes_until_daily_check_hour
          // on the Python side) -- every run after that just follows the
          // fixed `minutes` interval above, same as before this existed.
          final delayMinutes = int.tryParse(args['initial_delay_minutes'] ?? '') ?? 0;
          await Workmanager().cancelByUniqueName(kNotifyUniqueName);
          await Workmanager().registerPeriodicTask(
            kNotifyUniqueName,
            kNotifyTaskName,
            frequency: Duration(minutes: minutes),
            initialDelay: Duration(minutes: delayMinutes < 0 ? 0 : delayMinutes),
            existingWorkPolicy: ExistingWorkPolicy.replace,
            constraints: Constraints(networkType: NetworkType.not_required),
            inputData: {
              'db_path': dbPath,
              'config_json': args['config_json'] ?? '{}',
            },
          );
          return 'ok';

        case 'cancel_notifications':
          if (Platform.isAndroid) {
            await Workmanager().cancelByUniqueName(kNotifyUniqueName);
          }
          return 'ok';

        case 'cancel_test_notification':
          // Lets the settings screen cancel a pending delayed test (e.g.
          // the admin picked a delay, then changed their mind before
          // leaving the app) instead of it firing anyway later.
          if (Platform.isAndroid) {
            await Workmanager().cancelByUniqueName(kTestNotifyUniqueName);
          }
          return 'ok';

        case 'send_test_notification':
          // Fires one real Android notification through the exact same
          // channel/plugin instance the closed-app background check uses
          // (kNotifyChannelId / _localNotifications), so "it worked here"
          // actually means the real alert channel is reachable -- not just
          // that some other, unrelated notification path works. No-op on
          // iOS/desktop/web, same as the rest of this bridge.
          if (!Platform.isAndroid) return 'ok';
          await _showLocalTestNotification(
            title: args['title'] ?? '',
            body: args['body'] ?? '',
          );
          return 'ok';

        case 'schedule_test_notification':
          // The "close the app and wait" variant of the test above: same
          // notification, but fired later by a one-off WorkManager task
          // instead of immediately -- so it can actually prove delivery
          // works while the app is fully closed, which send_test_notification
          // (fired synchronously, app still open) cannot. No-op on
          // iOS/desktop/web, same as the rest of this bridge.
          if (!Platform.isAndroid) return 'ok';
          final delaySeconds = int.tryParse(args['delay_seconds'] ?? '') ?? 30;
          await Workmanager().cancelByUniqueName(kTestNotifyUniqueName);
          await Workmanager().registerOneOffTask(
            kTestNotifyUniqueName,
            kTestNotifyTaskName,
            initialDelay: Duration(seconds: delaySeconds < 5 ? 5 : delaySeconds),
            existingWorkPolicy: ExistingWorkPolicy.replace,
            constraints: Constraints(networkType: NetworkType.not_required),
            inputData: {
              'title': args['title'] ?? '',
              'body': args['body'] ?? '',
            },
          );
          return 'ok';

        case 'request_notification_permission':
          if (!Platform.isAndroid) return 'ok';
          await _ensureLocalNotificationsInitialized();
          final granted = await _localNotifications
              .resolvePlatformSpecificImplementation<AndroidFlutterLocalNotificationsPlugin>()
              ?.requestNotificationsPermission();
          return (granted ?? true) ? 'ok' : 'denied';

        case 'init_sound':
          // Best-effort warm-up, normally fired once at app startup (see
          // main.py's _preload_sound_pools) so the first real toast of the
          // session doesn't pay the one-time asset-decode cost before it
          // can play its tone. play_sound below re-runs this anyway (a
          // no-op once loaded), so this always returns 'ok' even if the
          // load itself partially failed -- individual kind failures are
          // logged in sound_pool.dart, not surfaced as an error here, same
          // "never block on sound" posture as the rest of this bridge.
          await ensureSoundPoolsLoaded();
          return 'ok';

        case 'play_sound':
          final kind = args['kind'] ?? '';
          final volume = double.tryParse(args['volume'] ?? '') ?? 1.0;
          if (kind.isEmpty) return 'ok';
          await playPoolSound(kind, volume);
          return 'ok';

        case 'diagnose_sound':
          // Backs the admin "تشخيص المشكلة" button (see native_files.py's
          // diagnose_sound()). 'retry' re-attempts kinds that failed to
          // load earlier in this session instead of just re-reporting the
          // same cached failure.
          final retry = args['retry'] == '1';
          final kinds = await diagnoseSoundPools(forceRetryFailed: retry);
          return jsonEncode({
            'platform': Platform.operatingSystem,
            'kinds': kinds,
          });

        case 'share_pdf':
          // Backward-compatible native method. New Python code calls create_pdf
          // then share_file, but this path deliberately uses the same shareXFiles
          // mechanism as backup sharing too.
          final file = await createPdfFile(args['html'] ?? '', args['filename'] ?? 'nano-report.pdf');
          final result = await Share.shareXFiles(
            [XFile(file.path, mimeType: 'application/pdf')],
            subject: args['filename'],
          );
          return result.status == ShareResultStatus.dismissed ? 'cancelled' : 'ok';

        case 'push_home_widget':
          // Immediate (app-open) path for PHASE10's home screen widget --
          // Python already has the fresh numbers in memory right after a
          // sale/receipt/payment posts (see DashboardService), so this skips
          // straight to updating the widget instead of waiting for the
          // periodic WorkManager pass in _pushHomeWidgetSnapshot below,
          // which only exists to keep the widget fresh while the app is
          // closed and nothing else can supply the numbers.
          if (!Platform.isAndroid) return 'ok';
          await _pushHomeWidgetJson(args['snapshot_json'] ?? '{}');
          return 'ok';

        default:
          return null;
      }
    } catch (error) {
      debugPrint('flet_native_files error: $method $error');
      return 'error:$error';
    }
  }

  @override
  void dispose() {
    widget.backend.unsubscribeMethods(widget.control.id);
    disposeSoundPools();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => const SizedBox.shrink();
}

/// Full-screen barcode/QR scanner. Pops with the decoded string on a
/// successful read, or `null` if the user backs out manually.
///
/// Guards against `mobile_scanner`'s `onDetect` firing multiple times per
/// frame/burst (a known behavior on some Android camera stacks) with a
/// `_handled` flag, so we never try to pop the route twice.
class _BarcodeScanPage extends StatefulWidget {
  const _BarcodeScanPage();

  @override
  State<_BarcodeScanPage> createState() => _BarcodeScanPageState();
}

class _BarcodeScanPageState extends State<_BarcodeScanPage>
    with SingleTickerProviderStateMixin {
  // autoStart: false -- we start the camera ourselves in initState() inside
  // a try/catch. With the default autoStart:true, MobileScanner starts the
  // camera internally and (on this package version) swallows a denied/failed
  // permission as a silent black preview: no exception surfaces anywhere,
  // onDetect never fires, and the user's only way out is the back button --
  // which pops with null and looks from the Python side exactly like a
  // deliberate cancel. Starting manually lets us catch that failure and
  // actually tell the user why nothing is happening instead of showing them
  // a dead camera view.
  final MobileScannerController _controller = MobileScannerController(
    autoStart: false,
    detectionSpeed: DetectionSpeed.noDuplicates,
    // Previously restricted to a 7-format allow-list (EAN-13/8, UPC-A/E,
    // Code128/39, QR). That list looked reasonable for "typical retail
    // barcodes", but it meant the scanner would run perfectly -- camera on,
    // live preview, no error -- and simply never fire onDetect for any
    // barcode using a format outside that list (Code93, Codabar, ITF,
    // PDF417, Data Matrix, Aztec, etc.), which is indistinguishable from
    // "not working" to whoever's holding the phone. Omitting `formats`
    // entirely makes mobile_scanner attempt every format it supports.
  );
  bool _handled = false;
  bool _starting = true;
  String? _startError;
  StreamSubscription<BarcodeCapture>? _subscription;
  // Diagnostic only, kept for debug builds (see kDebugMode gate in build()
  // below): what the barcode stream actually delivers. After several rounds
  // of guessing at this from Python-side symptoms alone, this makes the
  // real Dart/ML-Kit behavior visible instead of inferring it indirectly
  // through what does or doesn't land back in the item editor. Hidden from
  // release builds now -- it was raw telemetry, not something a cashier
  // scanning a bag of rice needs to see.
  String _debugInfo = 'بانتظار أول اكتشاف...';

  // Pulsing scan-line inside the viewfinder -- the single biggest visual
  // cue that separates "a live, working scanner" from "a static camera
  // preview with a rectangle drawn on it".
  late final AnimationController _scanLineController = AnimationController(
    vsync: this,
    duration: const Duration(milliseconds: 1600),
  )..repeat(reverse: true);

  // Pinch-to-zoom. mobile_scanner doesn't wire this up on its own; track a
  // 0.0-1.0 fraction and forward it to the controller on two-finger scale
  // gestures over the preview, with a native-camera-style side indicator
  // that only appears while actively pinching.
  double _zoom = 0.0;
  double _zoomAtGestureStart = 0.0;
  bool _showZoomIndicator = false;
  Timer? _zoomIndicatorTimer;

  static const Color _accent = Color(0xFF0F766E); // matches Colors.PRIMARY in theme.py
  static const double _frameWidth = 270;
  static const double _frameHeight = 200;

  @override
  void initState() {
    super.initState();
    // IMPORTANT: subscribe to controller.barcodes directly instead of using
    // MobileScanner's `onDetect:` widget parameter. mobile_scanner's own
    // documented usage pattern for manually-controlled start() (autoStart:
    // false, calling controller.start() yourself) listens to the stream
    // directly -- it does not pair manual start() with the widget's
    // onDetect callback. That combination is what this whole scan flow was
    // actually using, and it lines up exactly with the observed symptom:
    // camera preview visibly live and in focus, yet onDetect never firing
    // even once, not even with an empty result, across several seconds of
    // continuous scanning.
    _subscription = _controller.barcodes.listen(_onDetect);
    _startCamera();
  }

  Future<void> _startCamera() async {
    setState(() {
      _starting = true;
      _startError = null;
    });
    try {
      await _controller.start();
      if (!mounted) return;
      setState(() => _starting = false);
    } catch (error) {
      if (!mounted) return;
      setState(() {
        _starting = false;
        _startError =
            'تعذر تشغيل الكاميرا. قد يكون إذن الكاميرا مرفوضًا لهذا التطبيق.\n'
            'افتح إعدادات النظام > التطبيقات > Nano > الأذونات، فعّل إذن '
            'الكاميرا، ثم عد وأعد المحاولة.\n\n'
            'تفاصيل: $error';
      });
    }
  }

  Future<void> _onDetect(BarcodeCapture capture) async {
    if (_handled) return;

    if (capture.barcodes.isEmpty) {
      setState(() => _debugInfo = 'onDetect استُدعيت لكن بلا أي باركود (${DateTime.now().toIso8601String().substring(11, 19)})');
      return;
    }

    for (final barcode in capture.barcodes) {
      // rawValue can legitimately be null for some symbologies/encodings
      // (a documented ML Kit behavior, not specific to this app) even
      // though a barcode was genuinely detected -- displayValue is ML Kit's
      // own human-readable fallback for exactly that case, so try it too
      // instead of treating a null rawValue as "nothing was found".
      final value = barcode.rawValue ?? barcode.displayValue;
      if (value != null && value.trim().isNotEmpty) {
        // Set the guard *before* the first await so a second onDetect
        // firing while we're stopping the camera can't race in here too.
        _handled = true;
        // Immediate tactile confirmation -- fires before the camera even
        // finishes stopping, so the person holding the phone feels the hit
        // the instant a code is recognized instead of waiting on the
        // teardown/pop round-trip below.
        HapticFeedback.mediumImpact();
        // Continuous stocktake mode (see stocktake_view.py's scan_loop)
        // pops this page with the code, then *immediately* re-invokes
        // scan_barcode() to push a brand-new _BarcodeScanPage with a
        // brand-new MobileScannerController for the next item. Popping
        // right away (old behaviour) tears down this page -- and starts
        // releasing the platform camera session -- at the exact same
        // moment the next controller tries to acquire it. On several
        // Android camera stacks that race leaves the *new* session with a
        // black preview that never recovers (no error, no onDetect,
        // nothing -- exactly the "captures the first item then goes
        // black and won't respond" symptom reported for continuous scan).
        // Explicitly stopping and awaiting that here before popping
        // guarantees the camera is actually released first.
        _subscription?.cancel();
        try {
          await _controller.stop();
        } catch (error) {
          debugPrint('nano scan: controller.stop() before pop failed: $error');
        }
        if (!mounted) return;
        Navigator.of(context).pop(value.trim());
        return;
      }
    }

    // Every barcode this frame had both rawValue and displayValue empty --
    // genuinely detected something, but couldn't extract any text from it.
    // Surface the format(s) so we actually know what's being pointed at.
    final formats = capture.barcodes.map((b) => b.format.name).join(', ');
    setState(() => _debugInfo =
        'تم اكتشاف باركود لكن بلا قيمة نصية -- النوع: $formats (${DateTime.now().toIso8601String().substring(11, 19)})');
  }

  void _onScaleStart(ScaleStartDetails _) {
    _zoomAtGestureStart = _zoom;
  }

  void _onScaleUpdate(ScaleUpdateDetails details) {
    if (details.pointerCount < 2) return; // single-finger drags aren't zoom intent
    final next = (_zoomAtGestureStart + (details.scale - 1) / 3).clamp(0.0, 1.0);
    if ((next - _zoom).abs() < 0.004) return;
    setState(() {
      _zoom = next;
      _showZoomIndicator = true;
    });
    try {
      _controller.setZoomScale(_zoom);
    } catch (error) {
      debugPrint('nano scan: setZoomScale failed: $error');
    }
    _zoomIndicatorTimer?.cancel();
    _zoomIndicatorTimer = Timer(const Duration(milliseconds: 900), () {
      if (mounted) setState(() => _showZoomIndicator = false);
    });
  }

  @override
  void dispose() {
    // _onDetect already cancels the subscription and stops the controller
    // on the success path above -- this remains as the fallback for every
    // *other* way the page can close (manual back button, torch/permission
    // error screen dismissed, etc.), where that explicit stop never ran.
    _subscription?.cancel();
    _controller.dispose();
    _scanLineController.dispose();
    _zoomIndicatorTimer?.cancel();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final size = MediaQuery.of(context).size;
    final frame = Rect.fromCenter(
      center: Offset(size.width / 2, size.height / 2 - 24),
      width: _frameWidth,
      height: _frameHeight,
    );

    return Scaffold(
      backgroundColor: Colors.black,
      extendBodyBehindAppBar: true,
      appBar: _buildAppBar(),
      body: _startError != null
          ? _buildErrorBody()
          : _starting
              ? const Center(
                  child: CircularProgressIndicator(color: _accent),
                )
              : GestureDetector(
                  onScaleStart: _onScaleStart,
                  onScaleUpdate: _onScaleUpdate,
                  child: Stack(
                    fit: StackFit.expand,
                    children: [
                      MobileScanner(
                        controller: _controller,
                        // mobile_scanner 6.0.10 has an open upstream bug
                        // (juliansteenbakker/mobile_scanner#1454) where its
                        // built-in error overlay ("An unexpected error
                        // occurred.") pops up intermittently in release
                        // builds even though the camera stream and onDetect
                        // keep working fine underneath it -- it's a
                        // spurious display glitch, not an actual scan
                        // failure. The default errorBuilder blocks the
                        // whole preview with an opaque card, making the
                        // scanner look dead even though it isn't.
                        // Overriding it to stay out of the way (just log
                        // for diagnostics) keeps the live camera/
                        // viewfinder/onDetect visible and usable instead
                        // of hiding it behind that false error.
                        errorBuilder: (context, error, child) {
                          debugPrint('mobile_scanner transient error overlay suppressed: $error');
                          return const SizedBox.shrink();
                        },
                      ),
                      _buildDimOverlay(frame, size),
                      _buildViewfinder(frame),
                      _buildHintPill(frame),
                      if (_showZoomIndicator) _buildZoomIndicator(),
                      // Diagnostics stay available to whoever's building/
                      // debugging the app, but never ship to a release APK
                      // -- the amber telemetry strip was exactly the kind
                      // of unfinished-looking clutter that made the old
                      // screen read as a debug build rather than a
                      // finished product.
                      if (kDebugMode) _buildDebugBanner(),
                    ],
                  ),
                ),
    );
  }

  PreferredSizeWidget _buildAppBar() {
    return AppBar(
      backgroundColor: Colors.transparent,
      elevation: 0,
      flexibleSpace: Container(
        decoration: BoxDecoration(
          gradient: LinearGradient(
            begin: Alignment.topCenter,
            end: Alignment.bottomCenter,
            colors: [Colors.black.withOpacity(0.75), Colors.transparent],
          ),
        ),
      ),
      leading: _circleIconButton(
        icon: Icons.close_rounded,
        onPressed: () => Navigator.of(context).maybePop(),
      ),
      title: const Text(
        'مسح الباركود',
        style: TextStyle(color: Colors.white, fontWeight: FontWeight.w600, fontSize: 17),
      ),
      centerTitle: true,
      actions: [
        if (_startError == null)
          ValueListenableBuilder(
            valueListenable: _controller,
            builder: (context, state, child) {
              final on = state.torchState == TorchState.on;
              return _circleIconButton(
                icon: on ? Icons.flash_on_rounded : Icons.flash_off_rounded,
                active: on,
                onPressed: () => _controller.toggleTorch(),
              );
            },
          ),
        const SizedBox(width: 6),
      ],
    );
  }

  Widget _circleIconButton({
    required IconData icon,
    required VoidCallback onPressed,
    bool active = false,
  }) {
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 6),
      child: Material(
        color: active ? _accent.withOpacity(0.9) : Colors.white.withOpacity(0.16),
        shape: const CircleBorder(),
        child: InkWell(
          customBorder: const CircleBorder(),
          onTap: onPressed,
          child: Padding(
            padding: const EdgeInsets.all(9),
            child: Icon(icon, color: Colors.white, size: 20),
          ),
        ),
      ),
    );
  }

  Widget _buildErrorBody() {
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(24),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            const Icon(Icons.no_photography_outlined, color: Colors.white70, size: 48),
            const SizedBox(height: 16),
            Text(
              _startError!,
              textAlign: TextAlign.center,
              style: const TextStyle(color: Colors.white70, fontSize: 13),
            ),
            const SizedBox(height: 20),
            FilledButton(
              style: FilledButton.styleFrom(backgroundColor: _accent),
              onPressed: _startCamera,
              child: const Text('إعادة المحاولة'),
            ),
          ],
        ),
      ),
    );
  }

  // Darkens everything outside the scan frame (four strips around it)
  // instead of a plain unstyled camera feed, so the eye is pulled straight
  // to the cutout -- the same "spotlight" treatment modern scanners
  // (Google Lens, banking-app QR pay, WhatsApp Web linking) all use.
  Widget _buildDimOverlay(Rect frame, Size size) {
    const dim = Colors.black54;
    return IgnorePointer(
      child: Stack(
        children: [
          Positioned(left: 0, right: 0, top: 0, height: frame.top, child: Container(color: dim)),
          Positioned(left: 0, right: 0, top: frame.bottom, bottom: 0, child: Container(color: dim)),
          Positioned(left: 0, top: frame.top, width: frame.left, height: frame.height, child: Container(color: dim)),
          Positioned(right: 0, top: frame.top, width: size.width - frame.right, height: frame.height, child: Container(color: dim)),
        ],
      ),
    );
  }

  Widget _buildViewfinder(Rect frame) {
    const radius = 20.0;
    return Positioned.fromRect(
      rect: frame,
      child: IgnorePointer(
        child: Stack(
          clipBehavior: Clip.none,
          children: [
            Container(
              decoration: BoxDecoration(
                border: Border.all(color: Colors.white.withOpacity(0.25), width: 1),
                borderRadius: BorderRadius.circular(radius),
              ),
            ),
            ClipRRect(
              borderRadius: BorderRadius.circular(radius),
              child: SizedBox(
                width: frame.width,
                height: frame.height,
                child: Stack(
                  children: [
                    AnimatedBuilder(
                      animation: _scanLineController,
                      builder: (context, child) {
                        final top = _scanLineController.value * (frame.height - 3);
                        return Positioned(
                          top: top,
                          left: 14,
                          right: 14,
                          child: Container(
                            height: 2.4,
                            decoration: BoxDecoration(
                              borderRadius: BorderRadius.circular(2),
                              gradient: LinearGradient(
                                colors: [_accent.withOpacity(0), _accent, _accent.withOpacity(0)],
                              ),
                              boxShadow: [BoxShadow(color: _accent.withOpacity(0.55), blurRadius: 6)],
                            ),
                          ),
                        );
                      },
                    ),
                  ],
                ),
              ),
            ),
            ..._corners(),
          ],
        ),
      ),
    );
  }

  // Four bracket corners (⌜ ⌝ ⌞ ⌟) built from small paired bars instead of
  // one plain rectangle border -- the corner-only style is what reads as
  // "camera/scanner UI" at a glance rather than "a box was drawn here".
  List<Widget> _corners() {
    const len = 26.0;
    const thick = 4.0;
    Widget bar({required double width, required double height}) => Container(
          width: width,
          height: height,
          decoration: BoxDecoration(color: _accent, borderRadius: BorderRadius.circular(thick)),
        );
    return [
      Positioned(top: -2, left: -2, child: bar(width: thick, height: len)),
      Positioned(top: -2, left: -2, child: bar(width: len, height: thick)),
      Positioned(top: -2, right: -2, child: bar(width: thick, height: len)),
      Positioned(top: -2, right: -2, child: bar(width: len, height: thick)),
      Positioned(bottom: -2, left: -2, child: bar(width: thick, height: len)),
      Positioned(bottom: -2, left: -2, child: bar(width: len, height: thick)),
      Positioned(bottom: -2, right: -2, child: bar(width: thick, height: len)),
      Positioned(bottom: -2, right: -2, child: bar(width: len, height: thick)),
    ];
  }

  Widget _buildHintPill(Rect frame) {
    return Positioned(
      top: frame.bottom + 18,
      left: 0,
      right: 0,
      child: IgnorePointer(
        child: Center(
          child: Container(
            padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 9),
            decoration: BoxDecoration(
              color: Colors.black.withOpacity(0.5),
              borderRadius: BorderRadius.circular(30),
            ),
            child: const Row(
              mainAxisSize: MainAxisSize.min,
              children: [
                Icon(Icons.qr_code_scanner_rounded, color: Colors.white70, size: 16),
                SizedBox(width: 8),
                Text(
                  'وجّه الكاميرا نحو الباركود',
                  style: TextStyle(color: Colors.white, fontSize: 13, fontWeight: FontWeight.w500),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }

  Widget _buildZoomIndicator() {
    return Positioned(
      right: 18,
      top: 0,
      bottom: 0,
      child: IgnorePointer(
        child: Center(
          child: Container(
            width: 34,
            padding: const EdgeInsets.symmetric(vertical: 14, horizontal: 6),
            decoration: BoxDecoration(color: Colors.black54, borderRadius: BorderRadius.circular(20)),
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                const Icon(Icons.zoom_in_rounded, color: Colors.white70, size: 16),
                const SizedBox(height: 8),
                SizedBox(
                  height: 90,
                  child: RotatedBox(
                    quarterTurns: 3,
                    child: LinearProgressIndicator(
                      value: _zoom,
                      backgroundColor: Colors.white24,
                      valueColor: const AlwaysStoppedAnimation(_accent),
                      minHeight: 4,
                    ),
                  ),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }

  // Temporary on-screen diagnostics -- shows exactly what ML Kit is seeing
  // per frame, so a failed scan reports real information back instead of
  // just "didn't work". Debug builds only; see the kDebugMode gate above.
  Widget _buildDebugBanner() {
    return Positioned(
      bottom: 8,
      left: 8,
      right: 8,
      child: Container(
        padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
        decoration: BoxDecoration(
          color: Colors.black54,
          borderRadius: BorderRadius.circular(8),
        ),
        child: Text(
          _debugInfo,
          textAlign: TextAlign.center,
          style: const TextStyle(color: Colors.amberAccent, fontSize: 11),
        ),
      ),
    );
  }
}
