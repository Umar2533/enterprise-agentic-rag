import 'package:flutter/material.dart';

import '../../../core/constants/api_constants.dart';
import '../../../core/errors/api_exception.dart';
import '../../../core/network/api_client.dart';
import '../../../core/storage/app_session.dart';
import '../../../features/chat/data/models/collection_summary.dart';
import '../../../features/chat/data/services/chat_api_service.dart';
import '../../../shared/widgets/app_card.dart';
import '../../../shared/widgets/error_view.dart';
import '../../../shared/widgets/loading_view.dart';
import '../../../shared/widgets/status_badge.dart';

class KnowledgeBaseScreen extends StatefulWidget {
  const KnowledgeBaseScreen({required this.session, super.key});

  final AppSession session;

  @override
  State<KnowledgeBaseScreen> createState() => _KnowledgeBaseScreenState();
}

class _KnowledgeBaseScreenState extends State<KnowledgeBaseScreen> {
  late ChatApiService _service;
  List<CollectionSummary> _collections = [];
  String? _error;
  bool _loading = true;
  String? _selectingCollectionName;
  String? _deletingCollectionName;
  String? _loadingDetailsCollectionName;

  @override
  void initState() {
    super.initState();
    _service = _buildService();
    _load();
  }

  ChatApiService _buildService() {
    return ChatApiService(
      baseUrl: widget.session.backendUrl,
      apiClient: ApiClient(debugMode: widget.session.debugMode),
    );
  }

  Map<String, String>? get _knowledgeHeaders {
    final token = widget.session.jwtToken?.trim() ?? '';
    if (token.isEmpty) {
      return null;
    }
    final normalizedToken = token.toLowerCase().startsWith('bearer ')
        ? token.substring(7).trim()
        : token;
    if (normalizedToken.isEmpty) {
      return null;
    }
    return {
      ...widget.session.requestHeaders,
      'Authorization': 'Bearer $normalizedToken',
    };
  }

  String _messageForError(Object error) {
    if (error is ApiException && error.statusCode == 401) {
      return 'Please log in again';
    }
    return error.toString();
  }

  Future<void> _load() async {
    setState(() {
      _loading = true;
      _error = null;
    });
    final headers = _knowledgeHeaders;
    if (headers == null) {
      setState(() {
        _error = 'Please log in again';
        _loading = false;
      });
      return;
    }
    try {
      final collections = await _service.listCollections(headers: headers);
      if (mounted) {
        setState(() {
          _collections = collections;
          _loading = false;
        });
      }
    } catch (error) {
      if (mounted) {
        setState(() {
          _error = _messageForError(error);
          _loading = false;
        });
      }
    }
  }

  Future<void> _select(CollectionSummary collection) async {
    setState(() {
      _selectingCollectionName = collection.collectionName;
      _error = null;
    });
    try {
      final selected = await _service.selectCollection(
        collection,
        headers: _knowledgeHeaders,
      );
      await widget.session.activateSession(
        sessionId: selected.sessionId,
        collectionName: selected.collectionName,
        embeddingProvider: selected.embeddingProvider,
      );
      if (mounted) {
        setState(() => _selectingCollectionName = null);
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('Activated ${selected.collectionName}')),
        );
      }
    } catch (error) {
      if (mounted) {
        setState(() {
          _selectingCollectionName = null;
          _error = _messageForError(error);
        });
      }
    }
  }

  Future<void> _confirmDelete(CollectionSummary collection) async {
    if (_deletingCollectionName != null) {
      return;
    }
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (dialogContext) {
        return AlertDialog(
          title: const Text('Remove collection?'),
          content: Text(
            'Permanently delete "${collection.collectionName}" and its stored vectors? This cannot be undone.',
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.pop(dialogContext, false),
              child: const Text('Cancel'),
            ),
            FilledButton(
              onPressed: () => Navigator.pop(dialogContext, true),
              style: FilledButton.styleFrom(
                backgroundColor: Theme.of(dialogContext).colorScheme.error,
                foregroundColor: Theme.of(dialogContext).colorScheme.onError,
              ),
              child: const Text('Delete'),
            ),
          ],
        );
      },
    );
    if (confirmed == true && mounted) {
      await _delete(collection);
    }
  }

  Future<void> _delete(CollectionSummary collection) async {
    setState(() {
      _deletingCollectionName = collection.collectionName;
      _error = null;
    });
    try {
      await _service.deleteCollectionByName(
        collection.collectionName,
        headers: _knowledgeHeaders,
      );
      final wasActive =
          collection.collectionName == widget.session.collectionName;
      if (wasActive) {
        await widget.session.resetSession();
      }
      if (!mounted) {
        return;
      }
      setState(() {
        _collections = _collections
            .where((item) => item.collectionName != collection.collectionName)
            .toList();
        _deletingCollectionName = null;
      });
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('Deleted ${collection.collectionName}')),
      );
    } catch (error) {
      if (mounted) {
        setState(() {
          _deletingCollectionName = null;
          _error = _messageForError(error);
        });
      }
    }
  }

  Future<void> _showDetails(CollectionSummary collection) async {
    if (_loadingDetailsCollectionName != null) {
      return;
    }
    setState(() => _loadingDetailsCollectionName = collection.collectionName);
    try {
      final summary = await _service.getCollectionSummary(
        collection.collectionName,
        headers: _knowledgeHeaders,
      );
      if (!mounted) {
        return;
      }
      setState(() => _loadingDetailsCollectionName = null);
      await showModalBottomSheet<void>(
        context: context,
        isScrollControlled: true,
        showDragHandle: true,
        shape: const RoundedRectangleBorder(
          borderRadius: BorderRadius.vertical(top: Radius.circular(24)),
        ),
        builder: (sheetContext) =>
            _CollectionDetailsSheet(collection: collection, summary: summary),
      );
    } catch (error) {
      if (mounted) {
        setState(() => _loadingDetailsCollectionName = null);
        ScaffoldMessenger.of(
          context,
        ).showSnackBar(SnackBar(content: Text(_messageForError(error))));
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    if (_loading) {
      return const SafeArea(
        child: LoadingView(message: 'Loading collections...'),
      );
    }
    if (_error != null && _collections.isEmpty) {
      return SafeArea(
        child: ErrorView(
          title: 'Knowledge base unavailable',
          message: _error!,
          onRetry: _load,
        ),
      );
    }

    return SafeArea(
      child: RefreshIndicator(
        onRefresh: _load,
        child: ListView(
          padding: const EdgeInsets.all(16),
          children: [
            Row(
              children: [
                Expanded(
                  child: Text(
                    'Knowledge Base',
                    style: Theme.of(context).textTheme.headlineSmall?.copyWith(
                      fontWeight: FontWeight.w900,
                    ),
                  ),
                ),
                IconButton(
                  onPressed: _load,
                  icon: const Icon(Icons.refresh_rounded),
                  tooltip: 'Refresh',
                ),
              ],
            ),
            const SizedBox(height: 12),
            AppCard(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    'Active Session',
                    style: Theme.of(context).textTheme.titleMedium?.copyWith(
                      fontWeight: FontWeight.w900,
                    ),
                  ),
                  const SizedBox(height: 10),
                  _Line('Collection', widget.session.collectionName),
                  _Line('Session ID', widget.session.sessionId),
                  _Line('Embedding', widget.session.embeddingProvider),
                ],
              ),
            ),
            const SizedBox(height: 14),
            AppCard(
              child: DropdownButtonFormField<String>(
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
                        child: Text(
                          ApiConstants.embeddingProviderLabel(provider),
                        ),
                      ),
                    )
                    .toList(),
                onChanged: (value) {
                  if (value != null) {
                    widget.session.setEmbeddingProvider(value);
                  }
                },
              ),
            ),
            if (_error != null) ...[
              const SizedBox(height: 12),
              AppCard(
                child: Text(
                  _error!,
                  style: const TextStyle(color: Color(0xFFB91C1C)),
                ),
              ),
            ],
            const SizedBox(height: 14),
            Text(
              'Collections',
              style: Theme.of(
                context,
              ).textTheme.titleMedium?.copyWith(fontWeight: FontWeight.w900),
            ),
            const SizedBox(height: 8),
            if (_collections.isEmpty)
              const AppCard(
                child: Text('No collections returned by the backend.'),
              )
            else
              ..._collections.map((collection) {
                final isSelected =
                    collection.collectionName == widget.session.collectionName;
                final isSelecting =
                    _selectingCollectionName == collection.collectionName;
                final isDeleting =
                    _deletingCollectionName == collection.collectionName;
                final isLoadingDetails =
                    _loadingDetailsCollectionName == collection.collectionName;
                return Padding(
                  padding: const EdgeInsets.only(bottom: 10),
                  child: _CollectionCard(
                    collection: collection,
                    selected: isSelected,
                    loading: isSelecting,
                    deleting: isDeleting,
                    loadingDetails: isLoadingDetails,
                    disabled:
                        (_selectingCollectionName != null && !isSelecting) ||
                        _deletingCollectionName != null ||
                        _loadingDetailsCollectionName != null,
                    onSelect: () => _select(collection),
                    onDelete: () => _confirmDelete(collection),
                    onDetails: () => _showDetails(collection),
                  ),
                );
              }),
          ],
        ),
      ),
    );
  }
}

class _CollectionCard extends StatelessWidget {
  const _CollectionCard({
    required this.collection,
    required this.selected,
    required this.loading,
    required this.deleting,
    required this.loadingDetails,
    required this.disabled,
    required this.onSelect,
    required this.onDelete,
    required this.onDetails,
  });

  final CollectionSummary collection;
  final bool selected;
  final bool loading;
  final bool deleting;
  final bool loadingDetails;
  final bool disabled;
  final VoidCallback onSelect;
  final VoidCallback onDelete;
  final VoidCallback onDetails;

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    final providerColor = selected ? scheme.primary : const Color(0xFF2563EB);

    return AppCard(
      selected: selected,
      onTap: disabled || selected || loading ? null : onSelect,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              AnimatedContainer(
                duration: const Duration(milliseconds: 180),
                width: 42,
                height: 42,
                decoration: BoxDecoration(
                  color: selected
                      ? scheme.primary
                      : scheme.primary.withValues(alpha: .10),
                  borderRadius: BorderRadius.circular(12),
                ),
                child: Icon(
                  selected
                      ? Icons.check_circle_rounded
                      : Icons.folder_copy_rounded,
                  color: selected ? Colors.white : scheme.primary,
                ),
              ),
              const SizedBox(width: 12),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      collection.collectionName,
                      maxLines: 2,
                      overflow: TextOverflow.ellipsis,
                      style: Theme.of(context).textTheme.titleSmall?.copyWith(
                        fontWeight: FontWeight.w900,
                        color: selected ? scheme.primary : null,
                      ),
                    ),
                    const SizedBox(height: 5),
                    Text(
                      collection.filename.isEmpty
                          ? collection.source
                          : collection.filename,
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: Theme.of(context).textTheme.bodySmall,
                    ),
                  ],
                ),
              ),
              const SizedBox(width: 8),
              AnimatedSwitcher(
                duration: const Duration(milliseconds: 180),
                child: selected
                    ? const StatusBadge(
                        key: ValueKey('active'),
                        label: 'Active',
                        color: Color(0xFF16A34A),
                        icon: Icons.verified_rounded,
                      )
                    : StatusBadge(
                        key: const ValueKey('provider'),
                        label: collection.embeddingProvider,
                        color: providerColor,
                        icon: Icons.memory_rounded,
                      ),
              ),
            ],
          ),
          const SizedBox(height: 14),
          Row(
            children: [
              Expanded(
                child: Text(
                  collection.sessionId.isEmpty
                      ? 'Runtime session will be created on activation.'
                      : 'Session ${collection.sessionId}',
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: Theme.of(context).textTheme.bodySmall,
                ),
              ),
              const SizedBox(width: 10),
              IconButton(
                onPressed: disabled || loadingDetails ? null : onDetails,
                icon: loadingDetails
                    ? const SizedBox(
                        width: 18,
                        height: 18,
                        child: CircularProgressIndicator(strokeWidth: 2),
                      )
                    : const Icon(Icons.info_outline_rounded),
                tooltip: 'Collection details',
              ),
              IconButton(
                onPressed: disabled || loading || deleting ? null : onDelete,
                icon: deleting
                    ? const SizedBox(
                        width: 18,
                        height: 18,
                        child: CircularProgressIndicator(strokeWidth: 2),
                      )
                    : const Icon(Icons.delete_outline_rounded),
                color: scheme.error,
                tooltip: 'Delete collection',
              ),
              const SizedBox(width: 4),
              FilledButton.icon(
                onPressed: disabled || selected || loading || deleting
                    ? null
                    : onSelect,
                icon: loading
                    ? const SizedBox(
                        width: 16,
                        height: 16,
                        child: CircularProgressIndicator(strokeWidth: 2),
                      )
                    : Icon(
                        selected
                            ? Icons.check_rounded
                            : Icons.play_arrow_rounded,
                      ),
                label: Text(selected ? 'Active' : 'Activate'),
              ),
            ],
          ),
        ],
      ),
    );
  }
}

class _CollectionDetailsSheet extends StatelessWidget {
  const _CollectionDetailsSheet({
    required this.collection,
    required this.summary,
  });

  final CollectionSummary collection;
  final CollectionBuildSummary? summary;

  @override
  Widget build(BuildContext context) {
    final buildSummary = summary;
    return SafeArea(
      top: false,
      child: FractionallySizedBox(
        heightFactor: .78,
        child: Padding(
          padding: const EdgeInsets.fromLTRB(16, 0, 16, 16),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Row(
                children: [
                  Icon(
                    Icons.folder_copy_outlined,
                    color: Theme.of(context).colorScheme.primary,
                  ),
                  const SizedBox(width: 10),
                  Expanded(
                    child: Text(
                      'Collection Details',
                      style: Theme.of(context).textTheme.titleLarge?.copyWith(
                        fontWeight: FontWeight.w900,
                      ),
                    ),
                  ),
                  IconButton(
                    onPressed: () => Navigator.pop(context),
                    icon: const Icon(Icons.close_rounded),
                    tooltip: 'Close',
                  ),
                ],
              ),
              const SizedBox(height: 8),
              Expanded(
                child: SingleChildScrollView(
                  child: Column(
                    children: [
                      AppCard(
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Text(
                              'Collection',
                              style: Theme.of(context).textTheme.titleMedium
                                  ?.copyWith(fontWeight: FontWeight.w900),
                            ),
                            _DetailRow(
                              label: 'Collection Name',
                              value: _text(collection.collectionName),
                            ),
                            _DetailRow(
                              label: 'Filename',
                              value: _text(collection.filename),
                            ),
                            _DetailRow(
                              label: 'Embedding Provider',
                              value: _text(collection.embeddingProvider),
                            ),
                            if (collection.chunkCount != null)
                              _DetailRow(
                                label: 'Chunk Count',
                                value: collection.chunkCount.toString(),
                              ),
                            if (collection.bm25Ready != null)
                              _DetailRow(
                                label: 'BM25 Ready',
                                value: collection.bm25Ready! ? 'Yes' : 'No',
                              ),
                          ],
                        ),
                      ),
                      const SizedBox(height: 12),
                      AppCard(
                        child: buildSummary == null
                            ? const Text(
                                'No persisted build summary is available for this collection yet.',
                              )
                            : Column(
                                crossAxisAlignment: CrossAxisAlignment.start,
                                children: [
                                  Text(
                                    'Build Summary',
                                    style: Theme.of(context)
                                        .textTheme
                                        .titleMedium
                                        ?.copyWith(fontWeight: FontWeight.w900),
                                  ),
                                  _DetailRow(
                                    label: 'Document Name',
                                    value: _text(buildSummary.documentName),
                                  ),
                                  _DetailRow(
                                    label: 'Document Type',
                                    value: _text(
                                      buildSummary.documentType.toUpperCase(),
                                    ),
                                  ),
                                  _DetailRow(
                                    label: 'Document Units',
                                    value: buildSummary.documentUnits,
                                  ),
                                  _DetailRow(
                                    label: 'Chunks Created',
                                    value: _number(buildSummary.chunksCreated),
                                  ),
                                  _DetailRow(
                                    label: 'Vectors Stored',
                                    value: _number(buildSummary.vectorsStored),
                                  ),
                                  _DetailRow(
                                    label: 'Chunk Size',
                                    value: _number(buildSummary.chunkSize),
                                  ),
                                  _DetailRow(
                                    label: 'Chunk Overlap',
                                    value: _number(buildSummary.chunkOverlap),
                                  ),
                                  _DetailRow(
                                    label: 'Embedding Model',
                                    value: _text(buildSummary.embeddingModel),
                                  ),
                                  if (buildSummary.lastBuiltAt != null)
                                    _DetailRow(
                                      label: 'Build Timestamp',
                                      value: _formatTimestamp(
                                        buildSummary.lastBuiltAt!,
                                      ),
                                    ),
                                ],
                              ),
                      ),
                    ],
                  ),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }

  static String _text(String value) {
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

class _DetailRow extends StatelessWidget {
  const _DetailRow({required this.label, required this.value});

  final String label;
  final String value;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(top: 8),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          SizedBox(
            width: 132,
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

class _Line extends StatelessWidget {
  const _Line(this.label, this.value);

  final String label;
  final String value;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(top: 7),
      child: Row(
        children: [
          SizedBox(
            width: 105,
            child: Text(
              label,
              style: Theme.of(context).textTheme.bodySmall?.copyWith(
                color: const Color(0xFF64748B),
                fontWeight: FontWeight.w700,
              ),
            ),
          ),
          Expanded(
            child: Text(
              value.isEmpty ? 'Not set' : value,
              maxLines: 1,
              overflow: TextOverflow.ellipsis,
            ),
          ),
        ],
      ),
    );
  }
}
