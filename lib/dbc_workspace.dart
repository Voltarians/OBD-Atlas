import 'dart:io';

import 'package:file_picker/file_picker.dart';
import 'package:flutter/material.dart';

import 'core/dbc.dart';

class DbcWorkspace extends StatefulWidget {
  const DbcWorkspace({super.key});
  @override
  State<DbcWorkspace> createState() => _DbcWorkspaceState();
}

class _DbcWorkspaceState extends State<DbcWorkspace> {
  late Future<List<StoredDbc>> _definitions;
  bool _busy = false;

  @override
  void initState() { super.initState(); _refresh(); }
  void _refresh() => _definitions = DbcStore.instance.list();

  void _notice(String message) {
    if (mounted) ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(message)));
  }

  Future<void> _import() async {
    final picked = await FilePicker.pickFile(type: FileType.custom, allowedExtensions: const ['dbc']);
    final path = picked?.path;
    if (path == null) return;
    setState(() => _busy = true);
    try {
      final stored = await DbcStore.instance.importFile(File(path));
      if (mounted) setState(_refresh);
      _notice('Imported ${stored.name}: ${stored.messages} messages, ${stored.signals} signals');
    } catch (error) {
      _notice(error.toString());
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _export(StoredDbc definition) async {
    final path = await FilePicker.saveFile(dialogTitle: 'Export DBC', fileName: definition.name, type: FileType.custom, allowedExtensions: const ['dbc']);
    if (path == null) return;
    setState(() => _busy = true);
    try {
      final destination = path.toLowerCase().endsWith('.dbc') ? path : '$path.dbc';
      await DbcStore.instance.export(definition, destination);
      _notice('Exported ${definition.name}');
    } catch (error) {
      _notice(error.toString());
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) => ListView(
    padding: const EdgeInsets.all(20),
    children: [
      Text('DBC Definitions', style: Theme.of(context).textTheme.headlineMedium),
      const SizedBox(height: 4),
      const Text('Import evidence-backed CAN definitions and export portable .dbc files offline.'),
      const SizedBox(height: 20),
      Align(alignment: Alignment.centerLeft, child: FilledButton.icon(onPressed: _busy ? null : _import, icon: const Icon(Icons.file_open), label: const Text('Import DBC'))),
      const SizedBox(height: 12),
      FutureBuilder<List<StoredDbc>>(
        future: _definitions,
        builder: (context, snapshot) {
          if (snapshot.hasError) return Card(child: ListTile(leading: const Icon(Icons.error_outline), title: Text(snapshot.error.toString())));
          if (!snapshot.hasData) return const Center(child: CircularProgressIndicator());
          if (snapshot.data!.isEmpty) return const Card(child: ListTile(title: Text('No DBC definitions imported')));
          return Column(children: snapshot.data!.map((item) => Card(child: ListTile(
            leading: const Icon(Icons.account_tree),
            title: Text(item.name),
            subtitle: Text('${item.messages} messages • ${item.signals} signals\nSHA-256 ${item.sha256Hex}'),
            isThreeLine: true,
            trailing: IconButton(onPressed: _busy ? null : () => _export(item), icon: const Icon(Icons.download), tooltip: 'Export DBC'),
          ))).toList());
        },
      ),
    ],
  );
}
