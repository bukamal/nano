import 'dart:convert';
import 'dart:io';

import 'package:cross_file/cross_file.dart';
import 'package:file_picker/file_picker.dart';
import 'package:flet/flet.dart';
import 'package:flutter/material.dart';
import 'package:path_provider/path_provider.dart';
import 'package:pdf/pdf.dart';
import 'package:printing/printing.dart';
import 'package:share_plus/share_plus.dart';

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
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => const SizedBox.shrink();
}
