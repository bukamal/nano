import 'dart:io';

import 'package:flet/flet.dart';
import 'package:workmanager/workmanager.dart';
import 'native_files.dart';

CreateControlFactory createControl = (CreateControlArgs args) {
  switch (args.control.type) {
    case "flet_native_files":
      // PHASE9 fix: nothing in the Flet-generated app ever called
      // ensureInitialized(), so Workmanager().initialize() never ran and
      // the closed-app notification check was never actually registered
      // -- external notifications never fired. This factory runs once per
      // control creation (NativeFiles is a single control mounted at app
      // startup), and ensureInitialized() is idempotent, so initializing
      // here guarantees the background dispatcher exists before any
      // schedule_notifications() call reaches the Dart side.
      ensureInitialized();
      return FletNativeFilesControl(
        parent: args.parent,
        control: args.control,
        children: args.children,
        backend: args.backend,
      );
    default:
      return null;
  }
};

bool _workmanagerInitialized = false;

// Registers the background isolate entry point once, at app start, so a
// WorkManager periodic task can find it later even after the app process
// was killed and Android relaunches it just to run the task. Android-only:
// workmanager has no iOS/desktop/web implementation, and calling initialize
// there throws instead of no-op'ing. Idempotent: createControl may be
// invoked more than once, and Workmanager().initialize() must never run
// twice (the second call throws "Workmanager is already initialized").
void ensureInitialized() {
  if (_workmanagerInitialized) return;
  _workmanagerInitialized = true;
  if (Platform.isAndroid) {
    Workmanager().initialize(notificationCallbackDispatcher, isInDebugMode: false);
  }
}
