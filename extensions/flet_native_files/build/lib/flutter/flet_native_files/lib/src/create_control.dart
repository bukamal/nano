import 'dart:io';

import 'package:flet/flet.dart';
import 'package:workmanager/workmanager.dart';
import 'native_files.dart';

CreateControlFactory createControl = (CreateControlArgs args) {
  switch (args.control.type) {
    case "flet_native_files":
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

// Registers the background isolate entry point once, at app start, so a
// WorkManager periodic task can find it later even after the app process
// was killed and Android relaunches it just to run the task. Android-only:
// workmanager has no iOS/desktop/web implementation, and calling initialize
// there throws instead of no-op'ing.
void ensureInitialized() {
  if (Platform.isAndroid) {
    Workmanager().initialize(notificationCallbackDispatcher, isInDebugMode: false);
  }
}
