import 'package:flutter/material.dart';

import '../../../core/constants/api_constants.dart';
import '../../../core/network/api_client.dart';
import '../../../core/storage/app_session.dart';
import '../../../features/upload/data/models/picked_document.dart';
import '../../../features/upload/data/models/upload_result.dart';
import '../../../features/upload/data/services/native_file_picker.dart';
import '../../../features/upload/data/services/upload_api_service.dart';
import '../../../shared/widgets/app_card.dart';
import '../../../shared/widgets/status_badge.dart';

String _generateCollectionName({String? filename}) {
  final now = DateTime.now();
  String twoDigits(int value) => value.toString().padLeft(2, '0');
  final timestamp = '${now.year.toString().padLeft(4, '0')}'
      '${twoDigits(now.month)}${twoDigits(now.day)}_'
      '${twoDigits(now.hour)}${twoDigits(now.minute)}${twoDigits(now.second)}';

  var baseName = 'collection';
  if (filename != null && filename.isNotEmpty) {
    final extensionIndex = filename.lastIndexOf('.');
    final filenameStem = extensionIndex > 0
        ? filename.substring(0, extensionIndex)
        : filename;
    final sanitized = filenameStem
        .toLowerCase()
        .replaceAll(RegExp(r'[^a-z0-9]+'), '_')
        .replaceAll(RegExp(r'^_+|_+$'), '');
    if (sanitized.isNotEmpty) {
      baseName = sanitized;
    }
  }

  if (baseName.length > 46) {
    baseName = baseName.substring(0, 46).replaceFirst(RegExp(r'_+$'), '');
  }
  return '${baseName}_$timestamp';
}

class UploadScreen extends StatefulWidget {
  const UploadScreen({required this.session, super.key});

  final AppSession session;

  @override
  State<UploadScreen> createState() => _UploadScreenState();
}

class _UploadScreenState extends State<UploadScreen> {
  final TextEditingController _collectionController = TextEditingController(
    text: _generateCollectionName(),
  );
  final TextEditingController _chunkSizeController = TextEditingController(
    text: '700',
  );
  final TextEditingController _chunkOverlapController = TextEditingController(
    text: '80',
  );
  final TextEditingController _topKController = TextEditingController(text: '5');
  final TextEditingController _maxIterationsController = TextEditingController(
    text: '3',
  );
  PickedDocument? _file;
  UploadBuildSummary? _uploadSummary;
  String? _error;
  String? _message;
  bool _uploading = false;
  bool _useExisting = false;
  bool _advancedSettingsExpanded = false;
  bool _collectionNameManuallyEdited = false;

  @override
  void dispose() {
    _collectionController.dispose();
    _chunkSizeController.dispose();
    _chunkOverlapController.dispose();
    _topKController.dispose();
    _maxIterationsController.dispose();
    super.dispose();
  }

  Future<void> _pickFile() async {
    try {
      final picked = await NativeFilePicker().pickDocument();
      if (picked == null) {
        return;
      }
      final extension = picked.name.split('.').last.toLowerCase();
      if (!{'pdf', 'docx', 'doc', 'txt'}.contains(extension)) {
        setState(() => _error = 'Unsupported file type: .$extension');
        return;
      }
      if (!_collectionNameManuallyEdited) {
        _collectionController.text = _generateCollectionName(
          filename: picked.name,
        );
      }
      setState(() {
        _file = picked;
        _uploadSummary = null;
        _error = null;
        _message = null;
      });
    } catch (error) {
      setState(() => _error = error.toString());
    }
  }

  Future<void> _upload() async {
    final file = _file;
    if (file == null) {
      setState(() => _error = 'Choose a PDF, DOCX, DOC, or TXT file first.');
      return;
    }
    final collection = _collectionController.text.trim();
    if (collection.isEmpty) {
      setState(() => _error = 'Collection name is required.');
      return;
    }
    final chunkSize = int.tryParse(_chunkSizeController.text.trim());
    if (chunkSize == null || chunkSize <= 0) {
      setState(() => _error = 'Chunk size must be a whole number greater than 0.');
      return;
    }
    final chunkOverlap = int.tryParse(_chunkOverlapController.text.trim());
    if (chunkOverlap == null || chunkOverlap < 0) {
      setState(() => _error = 'Chunk overlap must be a whole number of 0 or greater.');
      return;
    }
    if (chunkOverlap >= chunkSize) {
      setState(() => _error = 'Chunk overlap must be less than chunk size.');
      return;
    }
    final topK = int.tryParse(_topKController.text.trim());
    if (topK == null || topK < 1) {
      setState(() => _error = 'Top K must be a whole number of at least 1.');
      return;
    }
    final maxIterations = int.tryParse(_maxIterationsController.text.trim());
    if (maxIterations == null || maxIterations < 1) {
      setState(
        () => _error = 'Max iterations must be a whole number of at least 1.',
      );
      return;
    }

    setState(() {
      _uploading = true;
      _uploadSummary = null;
      _error = null;
      _message = null;
    });

    try {
      final service = UploadApiService(
        baseUrl: widget.session.backendUrl,
        apiClient: ApiClient(debugMode: widget.session.debugMode),
      );
      final result = await service.uploadDocument(
        bytes: file.bytes,
        filename: file.name,
        collectionName: collection,
        embeddingProvider: widget.session.embeddingProvider,
        chunkSize: chunkSize,
        chunkOverlap: chunkOverlap,
        topK: topK,
        maxIterations: maxIterations,
        useExistingCollection: _useExisting,
        headers: widget.session.authHeaders,
      );
      await widget.session.activateSession(
        sessionId: result.sessionId,
        collectionName: result.collectionName,
        embeddingProvider: result.embeddingProvider,
      );
      if (mounted) {
        setState(() {
          _uploading = false;
          _message = result.message.isEmpty
              ? 'Knowledge base is ready.'
              : result.message;
          _uploadSummary = result.summary;
        });
      }
    } catch (error) {
      if (mounted) {
        setState(() {
          _uploading = false;
          _error = error.toString();
        });
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    final file = _file;
    return SafeArea(
      child: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          Text(
            'Upload Document',
            style: Theme.of(
              context,
            ).textTheme.headlineSmall?.copyWith(fontWeight: FontWeight.w900),
          ),
          const SizedBox(height: 8),
          Text(
            'Build a backend RAG session with /api/v1/upload/document.',
            style: Theme.of(
              context,
            ).textTheme.bodyMedium?.copyWith(color: const Color(0xFF64748B)),
          ),
          const SizedBox(height: 16),
          AppCard(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                TextField(
                  controller: _collectionController,
                  onChanged: (_) => _collectionNameManuallyEdited = true,
                  decoration: const InputDecoration(
                    labelText: 'Collection name',
                    prefixIcon: Icon(Icons.folder_rounded),
                  ),
                ),
                const SizedBox(height: 12),
                DropdownButtonFormField<String>(
                  initialValue:
                      ApiConstants.supportedEmbeddingProviders.contains(
                        widget.session.embeddingProvider,
                      )
                      ? widget.session.embeddingProvider
                      : ApiConstants.defaultEmbeddingProvider,
                  decoration: const InputDecoration(
                    labelText: 'Embedding provider',
                    prefixIcon: Icon(Icons.memory_rounded),
                  ),
                  items: ApiConstants.supportedEmbeddingProviders
                      .map(
                        (provider) => DropdownMenuItem(
                          value: provider,
                          child: Text(provider),
                        ),
                      )
                      .toList(),
                  onChanged: (value) {
                    if (value != null) {
                      widget.session.setEmbeddingProvider(value);
                    }
                  },
                ),
                const SizedBox(height: 10),
                SwitchListTile(
                  value: _useExisting,
                  onChanged: (value) => setState(() => _useExisting = value),
                  contentPadding: EdgeInsets.zero,
                  title: const Text('Use existing collection if available'),
                ),
                const SizedBox(height: 4),
                Container(
                  decoration: BoxDecoration(
                    color: Theme.of(context)
                        .colorScheme
                        .surfaceContainerHighest
                        .withValues(alpha: .42),
                    borderRadius: BorderRadius.circular(12),
                    border: Border.all(color: Theme.of(context).dividerColor),
                  ),
                  child: Column(
                    children: [
                      InkWell(
                        onTap: () => setState(
                          () => _advancedSettingsExpanded =
                              !_advancedSettingsExpanded,
                        ),
                        borderRadius: BorderRadius.circular(12),
                        child: Padding(
                          padding: const EdgeInsets.symmetric(
                            horizontal: 12,
                            vertical: 10,
                          ),
                          child: Row(
                            children: [
                              Icon(
                                Icons.tune_rounded,
                                size: 19,
                                color: Theme.of(context).colorScheme.primary,
                              ),
                              const SizedBox(width: 8),
                              Expanded(
                                child: Text(
                                  'Advanced settings',
                                  style: Theme.of(context)
                                      .textTheme
                                      .titleSmall
                                      ?.copyWith(fontWeight: FontWeight.w800),
                                ),
                              ),
                              Icon(
                                _advancedSettingsExpanded
                                    ? Icons.keyboard_arrow_up_rounded
                                    : Icons.keyboard_arrow_down_rounded,
                              ),
                            ],
                          ),
                        ),
                      ),
                      AnimatedSize(
                        duration: const Duration(milliseconds: 180),
                        curve: Curves.easeOutCubic,
                        child: _advancedSettingsExpanded
                            ? Padding(
                                padding: const EdgeInsets.fromLTRB(
                                  12,
                                  2,
                                  12,
                                  12,
                                ),
                                child: Column(
                                  children: [
                                    Row(
                                      children: [
                                        Expanded(
                                          child: _NumberField(
                                            controller: _chunkSizeController,
                                            label: 'Chunk Size',
                                          ),
                                        ),
                                        const SizedBox(width: 10),
                                        Expanded(
                                          child: _NumberField(
                                            controller: _chunkOverlapController,
                                            label: 'Chunk Overlap',
                                          ),
                                        ),
                                      ],
                                    ),
                                    const SizedBox(height: 10),
                                    Row(
                                      children: [
                                        Expanded(
                                          child: _NumberField(
                                            controller: _topKController,
                                            label: 'Top K',
                                          ),
                                        ),
                                        const SizedBox(width: 10),
                                        Expanded(
                                          child: _NumberField(
                                            controller:
                                                _maxIterationsController,
                                            label: 'Max Iterations',
                                          ),
                                        ),
                                      ],
                                    ),
                                  ],
                                ),
                              )
                            : const SizedBox.shrink(),
                      ),
                    ],
                  ),
                ),
                const SizedBox(height: 12),
                OutlinedButton.icon(
                  onPressed: _uploading ? null : _pickFile,
                  icon: const Icon(Icons.attach_file_rounded),
                  label: Text(file == null ? 'Choose file' : file.name),
                ),
                const SizedBox(height: 14),
                FilledButton.icon(
                  onPressed: _uploading ? null : _upload,
                  icon: _uploading
                      ? const SizedBox(
                          width: 18,
                          height: 18,
                          child: CircularProgressIndicator(strokeWidth: 2),
                        )
                      : const Icon(Icons.cloud_upload_rounded),
                  label: Text(
                    _uploading
                        ? 'Uploading and indexing...'
                        : 'Upload Document',
                  ),
                ),
              ],
            ),
          ),
          if (_message != null) ...[
            const SizedBox(height: 14),
            AppCard(
              child: Row(
                children: [
                  const StatusBadge(
                    label: 'Ready',
                    color: Color(0xFF16A34A),
                    icon: Icons.check_circle_rounded,
                  ),
                  const SizedBox(width: 10),
                  Expanded(child: Text(_message!)),
                ],
              ),
            ),
          ],
          if (_uploadSummary != null) ...[
            const SizedBox(height: 14),
            _UploadSummaryCard(summary: _uploadSummary!),
          ],
          if (_error != null) ...[
            const SizedBox(height: 14),
            AppCard(
              child: Text(
                _error!,
                style: const TextStyle(color: Color(0xFFB91C1C)),
              ),
            ),
          ],
        ],
      ),
    );
  }
}

class _NumberField extends StatelessWidget {
  const _NumberField({required this.controller, required this.label});

  final TextEditingController controller;
  final String label;

  @override
  Widget build(BuildContext context) {
    return TextField(
      controller: controller,
      keyboardType: TextInputType.number,
      decoration: InputDecoration(labelText: label),
    );
  }
}

class _UploadSummaryCard extends StatelessWidget {
  const _UploadSummaryCard({required this.summary});

  final UploadBuildSummary summary;

  @override
  Widget build(BuildContext context) {
    final rows = <(String, String)>[
      ('Collection Name', _value(summary.collectionName)),
      ('Document Name', _value(summary.documentName)),
      ('Document Type', _value(summary.documentType.toUpperCase())),
      ('Document Units', summary.documentUnits),
      ('Chunks Created', _number(summary.chunksCreated)),
      ('Vectors Stored', _number(summary.vectorsStored)),
      ('Chunk Size', _number(summary.chunkSize)),
      ('Chunk Overlap', _number(summary.chunkOverlap)),
      ('Embedding Model', _value(summary.embeddingModel)),
      if (summary.lastBuiltAt != null)
        ('Built At', _formatTimestamp(summary.lastBuiltAt!)),
    ];

    return AppCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Icon(
                Icons.analytics_outlined,
                size: 20,
                color: Theme.of(context).colorScheme.primary,
              ),
              const SizedBox(width: 8),
              Text(
                'Upload Summary',
                style: Theme.of(
                  context,
                ).textTheme.titleMedium?.copyWith(fontWeight: FontWeight.w900),
              ),
            ],
          ),
          const SizedBox(height: 10),
          ...rows.map(
            (row) => _SummaryRow(label: row.$1, value: row.$2),
          ),
        ],
      ),
    );
  }

  static String _value(String value) {
    return value.trim().isEmpty ? 'N/A' : value.trim();
  }

  static String _number(int? value) {
    return value?.toString() ?? 'N/A';
  }

  static String _formatTimestamp(DateTime value) {
    final local = value.toLocal();
    String twoDigits(int number) => number.toString().padLeft(2, '0');
    return '${local.year}-${twoDigits(local.month)}-${twoDigits(local.day)} '
        '${twoDigits(local.hour)}:${twoDigits(local.minute)}';
  }
}

class _SummaryRow extends StatelessWidget {
  const _SummaryRow({required this.label, required this.value});

  final String label;
  final String value;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(top: 7),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          SizedBox(
            width: 124,
            child: Text(
              label,
              style: Theme.of(context).textTheme.bodySmall?.copyWith(
                color: Theme.of(context).colorScheme.onSurfaceVariant,
                fontWeight: FontWeight.w700,
              ),
            ),
          ),
          const SizedBox(width: 8),
          Expanded(
            child: Text(
              value,
              style: Theme.of(
                context,
              ).textTheme.bodyMedium?.copyWith(fontWeight: FontWeight.w600),
            ),
          ),
        ],
      ),
    );
  }
}
