import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../../data/models/chat_request.dart';
import '../../data/models/chat_response.dart';
import '../../data/models/collection_summary.dart';
import '../../data/models/health_status.dart';
import '../../data/services/chat_api_service.dart';
import '../../../../core/constants/api_constants.dart';
import '../../../../core/network/api_client.dart';
import '../../../../core/storage/app_session.dart';
import '../widgets/chat_bubble.dart';
import '../widgets/chat_input_bar.dart';
import '../widgets/typing_indicator.dart';

class ChatScreen extends StatefulWidget {
  const ChatScreen({this.session, this.onExitChat, super.key});

  final AppSession? session;
  final VoidCallback? onExitChat;

  @override
  State<ChatScreen> createState() => _ChatScreenState();
}

class _ChatScreenState extends State<ChatScreen> {
  late final ChatApiService _apiService;
  final ScrollController _scrollController = ScrollController();

  final List<_ChatMessage> _messages = [];
  List<CollectionSummary> _collections = [];
  HealthStatus? _healthStatus;
  CollectionSummary? _activeCollection;
  String _sessionId = '';
  String? _errorMessage;
  String? _lastQuestion;
  bool _isBootstrapping = true;
  bool _isSending = false;
  bool _isStatusHeaderExpanded = false;
  bool _allowWebSearch = false;

  bool get _canSend => !_isSending && _sessionId.trim().isNotEmpty;

  @override
  void initState() {
    super.initState();
    _apiService = ChatApiService(
      baseUrl: widget.session?.backendUrl,
      apiClient: ApiClient(debugMode: widget.session?.debugMode ?? true),
    );
    _sessionId = widget.session?.sessionId ?? '';
    _bootstrap();
  }

  @override
  void dispose() {
    _scrollController.dispose();
    super.dispose();
  }

  Future<void> _bootstrap() async {
    setState(() {
      _isBootstrapping = true;
      _errorMessage = null;
    });

    try {
      final results = await Future.wait([
        _apiService.checkHealth(),
        _apiService.listCollections(
          headers: widget.session?.authHeaders ?? const <String, String>{},
        ),
      ]);
      if (!mounted) {
        return;
      }
      setState(() {
        _healthStatus = results[0] as HealthStatus;
        _collections = results[1] as List<CollectionSummary>;
        _isBootstrapping = false;
      });
    } catch (error) {
      if (!mounted) {
        return;
      }
      setState(() {
        _isBootstrapping = false;
        _errorMessage = error.toString();
      });
    }
  }

  Future<void> _activateCollection(CollectionSummary collection) async {
    setState(() {
      _errorMessage = null;
      _isSending = true;
    });

    try {
      final selected = await _apiService.selectCollection(
        collection,
        headers: widget.session?.authHeaders ?? const <String, String>{},
      );
      if (!mounted) {
        return;
      }
      setState(() {
        _activeCollection = selected;
        _sessionId = selected.sessionId;
        _isSending = false;
      });
      await widget.session?.activateSession(
        sessionId: selected.sessionId,
        collectionName: selected.collectionName,
        embeddingProvider: selected.embeddingProvider,
      );
      if (!mounted) {
        return;
      }
    } catch (error) {
      if (!mounted) {
        return;
      }
      setState(() {
        _isSending = false;
        _errorMessage = error.toString();
      });
    }
  }

  Future<void> _setSessionIdManually() async {
    final controller = TextEditingController(text: _sessionId);
    final value = await showDialog<String>(
      context: context,
      builder: (context) {
        return AlertDialog(
          title: const Text('Set Session ID'),
          content: TextField(
            controller: controller,
            autofocus: true,
            decoration: const InputDecoration(
              hintText: 'Paste session_id from upload response',
            ),
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.pop(context),
              child: const Text('Cancel'),
            ),
            FilledButton(
              onPressed: () => Navigator.pop(context, controller.text.trim()),
              child: const Text('Use Session'),
            ),
          ],
        );
      },
    );
    controller.dispose();

    if (value == null || value.trim().isEmpty || !mounted) {
      return;
    }

    setState(() {
      _sessionId = value.trim();
      _activeCollection = null;
      _errorMessage = null;
    });
    await widget.session?.activateSession(
      sessionId: value.trim(),
      collectionName: widget.session?.collectionName ?? '',
      embeddingProvider:
          widget.session?.embeddingProvider ??
          ApiConstants.defaultEmbeddingProvider,
    );
    if (!mounted) {
      return;
    }
  }

  Future<void> _sendMessage(String question) async {
    final trimmedQuestion = question.trim();
    if (trimmedQuestion.isEmpty || !_canSend) {
      return;
    }

    setState(() {
      _lastQuestion = trimmedQuestion;
      _errorMessage = null;
      _isSending = true;
      _messages.add(_ChatMessage.user(trimmedQuestion));
    });
    _scrollToBottom();

    try {
      final response = await _apiService.sendMessage(
        ChatRequest(
          sessionId: _sessionId.trim(),
          question: trimmedQuestion,
          allowWebSearch: _allowWebSearch,
        ),
        headers: widget.session?.authHeaders ?? const <String, String>{},
      );
      if (!mounted) {
        return;
      }
      setState(() {
        _messages.add(_ChatMessage.assistant(response));
        _isSending = false;
      });
      _scrollToBottom();
    } catch (error) {
      if (!mounted) {
        return;
      }
      setState(() {
        _isSending = false;
        _errorMessage = error.toString();
      });
      _scrollToBottom();
    }
  }

  void _retryLastQuestion() {
    final question = _lastQuestion;
    if (question == null || question.trim().isEmpty) {
      return;
    }
    _sendMessage(question);
  }

  Future<void> _copyConversationAsMarkdown() async {
    if (_messages.isEmpty) {
      _showCopyMessage('No conversation to copy');
      return;
    }

    await Clipboard.setData(ClipboardData(text: _conversationMarkdown()));
    if (!mounted) {
      return;
    }
    _showCopyMessage('Conversation copied as Markdown');
  }

  Future<void> _handleToolbarAction(_ChatToolbarAction action) async {
    await Future<void>.delayed(Duration.zero);
    if (action == _ChatToolbarAction.copyMarkdown) {
      await _copyConversationAsMarkdown();
    }
  }

  String _conversationMarkdown() {
    final buffer = StringBuffer('# Enterprise RAG Chat\n');
    for (final message in _messages) {
      buffer
        ..writeln()
        ..writeln(message.isUser ? '## User' : '## Assistant')
        ..writeln()
        ..writeln(message.text.trim());

      if (!message.isUser) {
        final metadataLines = _safeMetadataLines(message.metadata);
        if (metadataLines.isNotEmpty) {
          buffer
            ..writeln()
            ..writeln('### Metadata');
          for (final line in metadataLines) {
            buffer.writeln('- $line');
          }
        }

        final sourceLines = _sourceSummaryLines(message.sources);
        if (sourceLines.isNotEmpty) {
          buffer
            ..writeln()
            ..writeln('### Sources');
          for (var index = 0; index < sourceLines.length; index++) {
            buffer.writeln('${index + 1}. ${sourceLines[index]}');
          }
        }
      }
    }
    return buffer.toString().trimRight();
  }

  List<String> _safeMetadataLines(Map<String, dynamic> metadata) {
    final fields = <(String, Object?)>[
      ('Confidence', metadata['confidence_level'] ?? metadata['confidence']),
      ('Evaluation', metadata['evaluation'] ?? metadata['evaluation_status']),
      ('Retrieval mode', metadata['retrieval_mode']),
      ('Iterations', metadata['iteration_count'] ?? metadata['iterations']),
    ];
    return fields
        .where((field) => _hasExportValue(field.$2))
        .map((field) => '${field.$1}: ${field.$2}')
        .toList();
  }

  List<String> _sourceSummaryLines(List<Map<String, dynamic>> sources) {
    return sources.map((source) {
      final nested = source['metadata'];
      final metadata = nested is Map
          ? Map<String, dynamic>.from(nested)
          : const <String, dynamic>{};
      final isWeb = _isWebSource(source, metadata);
      final label =
          _sourceValue(
            source,
            metadata,
            isWeb
                ? const ['title', 'url', 'source']
                : const ['file_name', 'filename', 'document_title', 'source'],
          ) ??
          (isWeb ? 'Web source' : 'Document');
      final details = <String>[];
      final page = _sourceValue(source, metadata, const [
        'page_number',
        'page',
      ]);
      final chunk = _sourceValue(source, metadata, const [
        'chunk_id',
        'chunk_index',
      ]);
      final url = _sourceValue(source, metadata, const ['url', 'link']);
      if (!isWeb && page != null) {
        details.add('page $page');
      }
      if (!isWeb && chunk != null) {
        details.add('chunk $chunk');
      }
      if (isWeb && url != null && url != label) {
        details.add(url);
      }
      final prefix = isWeb ? 'Web' : 'Document';
      return details.isEmpty
          ? '$prefix: $label'
          : '$prefix: $label (${details.join(', ')})';
    }).toList();
  }

  bool _isWebSource(
    Map<String, dynamic> source,
    Map<String, dynamic> metadata,
  ) {
    final markers = [
      source['source_kind'],
      source['source_type'],
      source['retrieval_type'],
      source['source'],
      metadata['source_type'],
      metadata['retrieval_type'],
      metadata['source'],
    ];
    return markers.any(
          (value) => value?.toString().toLowerCase().contains('web') == true,
        ) ||
        _sourceValue(source, metadata, const ['url', 'link']) != null;
  }

  String? _sourceValue(
    Map<String, dynamic> source,
    Map<String, dynamic> metadata,
    List<String> keys,
  ) {
    for (final key in keys) {
      final direct = source[key]?.toString().trim() ?? '';
      if (direct.isNotEmpty) {
        return direct;
      }
      final nested = metadata[key]?.toString().trim() ?? '';
      if (nested.isNotEmpty) {
        return nested;
      }
    }
    return null;
  }

  bool _hasExportValue(Object? value) {
    return value != null && value.toString().trim().isNotEmpty;
  }

  void _showCopyMessage(String message) {
    final messenger = ScaffoldMessenger.of(context);
    messenger.hideCurrentSnackBar();
    messenger.showSnackBar(
      SnackBar(content: Text(message), duration: const Duration(seconds: 2)),
    );
  }

  void _scrollToBottom() {
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (!_scrollController.hasClients) {
        return;
      }
      _scrollController.animateTo(
        _scrollController.position.maxScrollExtent,
        duration: const Duration(milliseconds: 260),
        curve: Curves.easeOutCubic,
      );
    });
  }

  @override
  Widget build(BuildContext context) {
    final mediaQuery = MediaQuery.of(context);
    return LayoutBuilder(
      builder: (context, constraints) {
        final mediaAvailableHeight =
            mediaQuery.size.height - mediaQuery.viewInsets.bottom;
        final availableHeight = constraints.hasBoundedHeight
            ? constraints.maxHeight.clamp(0.0, mediaAvailableHeight)
            : mediaAvailableHeight;
        final keyboardOpen =
            mediaQuery.viewInsets.bottom > 0 ||
            (constraints.hasBoundedHeight &&
                constraints.maxHeight < mediaQuery.size.height);
        final useCompactStatusHeader =
            mediaQuery.orientation == Orientation.landscape ||
            availableHeight < 520;
        final hideStatusHeader =
            keyboardOpen &&
            (mediaQuery.orientation == Orientation.landscape ||
                availableHeight < 180);
        final useMinimalStatusHeader = useCompactStatusHeader && keyboardOpen;

        return Scaffold(
          appBar: AppBar(
            toolbarHeight: 56,
            titleSpacing: 16,
            leading: widget.onExitChat == null
                ? null
                : IconButton(
                    onPressed: widget.onExitChat,
                    icon: const Icon(Icons.arrow_back_rounded),
                    tooltip: 'Back to app',
                  ),
            title: const Text('Enterprise RAG'),
            actions: [
              PopupMenuButton<_ChatToolbarAction>(
                tooltip: 'Chat actions',
                onSelected: _handleToolbarAction,
                itemBuilder: (context) => [
                  PopupMenuItem(
                    value: _ChatToolbarAction.copyMarkdown,
                    enabled: _messages.isNotEmpty,
                    child: const Row(
                      children: [
                        Icon(Icons.copy_all_rounded, size: 19),
                        SizedBox(width: 10),
                        Text('Copy conversation as Markdown'),
                      ],
                    ),
                  ),
                ],
              ),
              IconButton(
                onPressed: () => setState(() => _messages.clear()),
                icon: const Icon(Icons.delete_sweep_rounded),
                tooltip: 'Clear chat',
              ),
              IconButton(
                onPressed: _bootstrap,
                icon: const Icon(Icons.refresh_rounded),
                tooltip: 'Refresh backend status',
              ),
            ],
          ),
          body: SafeArea(
            top: false,
            child: Column(
              children: [
                if (!hideStatusHeader)
                  _StatusHeader(
                    healthStatus: _healthStatus,
                    isLoading: _isBootstrapping,
                    sessionId: _sessionId,
                    activeCollection: _activeCollection,
                    sessionCollectionName: widget.session?.collectionName ?? '',
                    collections: _collections,
                    isExpanded: _isStatusHeaderExpanded,
                    forceCompact: useCompactStatusHeader,
                    minimal: useMinimalStatusHeader,
                    onToggleExpanded: () => setState(
                      () => _isStatusHeaderExpanded = !_isStatusHeaderExpanded,
                    ),
                    onActivateCollection: _activateCollection,
                    onSetSessionId: _setSessionIdManually,
                  ),
                if (_errorMessage != null && !hideStatusHeader)
                  _ErrorBanner(
                    message: _errorMessage!,
                    canRetry: _lastQuestion != null && _sessionId.isNotEmpty,
                    onRetry: _retryLastQuestion,
                    onDismiss: () => setState(() => _errorMessage = null),
                  ),
                Expanded(
                  child: _messages.isEmpty && !_isSending
                      ? _EmptyState(
                          hasSession: _sessionId.isNotEmpty,
                          hasCollections: _collections.isNotEmpty,
                        )
                      : ListView.separated(
                          controller: _scrollController,
                          keyboardDismissBehavior:
                              ScrollViewKeyboardDismissBehavior.onDrag,
                          padding: const EdgeInsets.fromLTRB(12, 12, 12, 14),
                          itemCount: _messages.length + (_isSending ? 1 : 0),
                          separatorBuilder: (_, _) =>
                              const SizedBox(height: 12),
                          itemBuilder: (context, index) {
                            if (_isSending && index == _messages.length) {
                              return const TypingIndicator();
                            }
                            final message = _messages[index];
                            return ChatBubble(
                              text: message.text,
                              isUser: message.isUser,
                              metadata: message.metadata,
                              sources: message.sources,
                            );
                          },
                        ),
                ),
                ChatInputBar(
                  enabled: _canSend,
                  webSearchEnabled: _allowWebSearch,
                  onWebSearchChanged: (value) {
                    setState(() => _allowWebSearch = value);
                  },
                  onSend: _sendMessage,
                ),
              ],
            ),
          ),
        );
      },
    );
  }
}

enum _ChatToolbarAction { copyMarkdown }

class _StatusHeader extends StatelessWidget {
  const _StatusHeader({
    required this.healthStatus,
    required this.isLoading,
    required this.sessionId,
    required this.activeCollection,
    required this.sessionCollectionName,
    required this.collections,
    required this.isExpanded,
    required this.forceCompact,
    required this.minimal,
    required this.onToggleExpanded,
    required this.onActivateCollection,
    required this.onSetSessionId,
  });

  final HealthStatus? healthStatus;
  final bool isLoading;
  final String sessionId;
  final CollectionSummary? activeCollection;
  final String sessionCollectionName;
  final List<CollectionSummary> collections;
  final bool isExpanded;
  final bool forceCompact;
  final bool minimal;
  final VoidCallback onToggleExpanded;
  final ValueChanged<CollectionSummary> onActivateCollection;
  final VoidCallback onSetSessionId;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final scheme = theme.colorScheme;
    final healthy = healthStatus?.isHealthy == true;
    final statusColor = healthy
        ? const Color(0xFF16A34A)
        : const Color(0xFFDC2626);
    final title =
        activeCollection?.collectionName ??
        (sessionCollectionName.isNotEmpty ? sessionCollectionName : null) ??
        (sessionId.isNotEmpty ? 'Manual session' : 'No active session');
    final subtitle = sessionId.isEmpty
        ? 'Activate a collection or paste a session id'
        : 'Session ${_shortSession(sessionId)}';
    final effectiveExpanded = isExpanded && !forceCompact;
    final statusLabel = isLoading
        ? 'Checking backend'
        : healthy
        ? '${healthStatus!.app} online'
        : 'Backend unavailable';

    return AnimatedSize(
      duration: const Duration(milliseconds: 180),
      curve: Curves.easeOutCubic,
      child: Container(
        color: theme.cardColor,
        padding: forceCompact
            ? const EdgeInsets.fromLTRB(8, 3, 8, 3)
            : const EdgeInsets.fromLTRB(10, 5, 10, 6),
        child: Container(
          padding: EdgeInsets.symmetric(
            horizontal: forceCompact ? 8 : 9,
            vertical: minimal ? 4 : 7,
          ),
          decoration: BoxDecoration(
            color: theme.cardColor,
            borderRadius: BorderRadius.circular(16),
            border: Border.all(color: theme.dividerColor),
            boxShadow: const [
              BoxShadow(
                color: Color(0x0A0F172A),
                blurRadius: 10,
                offset: Offset(0, 4),
              ),
            ],
          ),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Row(
                children: [
                  Container(
                    width: 22,
                    height: 22,
                    decoration: BoxDecoration(
                      color: (isLoading ? scheme.outline : statusColor)
                          .withValues(alpha: .12),
                      shape: BoxShape.circle,
                    ),
                    child: Icon(
                      healthy
                          ? Icons.cloud_done_rounded
                          : Icons.cloud_off_rounded,
                      size: 14,
                      color: isLoading ? scheme.outline : statusColor,
                    ),
                  ),
                  const SizedBox(width: 8),
                  Expanded(
                    child: minimal
                        ? Text(
                            '$statusLabel - $title',
                            maxLines: 1,
                            overflow: TextOverflow.ellipsis,
                            style: theme.textTheme.labelMedium?.copyWith(
                              fontWeight: FontWeight.w800,
                              color: scheme.onSurface,
                            ),
                          )
                        : Column(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              Text(
                                statusLabel,
                                maxLines: 1,
                                overflow: TextOverflow.ellipsis,
                                style: theme.textTheme.labelMedium?.copyWith(
                                  fontWeight: FontWeight.w800,
                                  color: scheme.onSurface,
                                ),
                              ),
                              if (!effectiveExpanded) ...[
                                const SizedBox(height: 1),
                                Text(
                                  title,
                                  maxLines: 1,
                                  overflow: TextOverflow.ellipsis,
                                  style: theme.textTheme.bodySmall?.copyWith(
                                    color: scheme.onSurfaceVariant,
                                    fontWeight: FontWeight.w600,
                                  ),
                                ),
                              ],
                            ],
                          ),
                  ),
                  if (effectiveExpanded) ...[
                    const SizedBox(width: 6),
                    _CompactActionButton(
                      icon: Icons.key_rounded,
                      label: 'Session',
                      onTap: onSetSessionId,
                    ),
                  ],
                  if (!forceCompact)
                    IconButton(
                      onPressed: onToggleExpanded,
                      icon: Icon(
                        effectiveExpanded
                            ? Icons.keyboard_arrow_up_rounded
                            : Icons.keyboard_arrow_down_rounded,
                      ),
                      iconSize: 20,
                      visualDensity: VisualDensity.compact,
                      tooltip: effectiveExpanded
                          ? 'Collapse session details'
                          : 'Expand session details',
                    ),
                ],
              ),
              if (effectiveExpanded) ...[
                const SizedBox(height: 7),
                Row(
                  children: [
                    Expanded(
                      child: Container(
                        padding: const EdgeInsets.symmetric(
                          horizontal: 10,
                          vertical: 7,
                        ),
                        decoration: BoxDecoration(
                          color: scheme.surfaceContainerHighest.withValues(
                            alpha: .5,
                          ),
                          borderRadius: BorderRadius.circular(12),
                          border: Border.all(color: theme.dividerColor),
                        ),
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Text(
                              title,
                              maxLines: 1,
                              overflow: TextOverflow.ellipsis,
                              style: theme.textTheme.labelLarge?.copyWith(
                                fontWeight: FontWeight.w900,
                                color: scheme.onSurface,
                              ),
                            ),
                            const SizedBox(height: 2),
                            Text(
                              subtitle,
                              maxLines: 1,
                              overflow: TextOverflow.ellipsis,
                              style: theme.textTheme.bodySmall?.copyWith(
                                color: scheme.onSurfaceVariant,
                              ),
                            ),
                          ],
                        ),
                      ),
                    ),
                    const SizedBox(width: 8),
                    PopupMenuButton<CollectionSummary>(
                      tooltip: 'Activate collection',
                      enabled: collections.isNotEmpty,
                      onSelected: onActivateCollection,
                      itemBuilder: (context) {
                        return collections.map((collection) {
                          return PopupMenuItem(
                            value: collection,
                            child: Text(
                              collection.collectionName,
                              overflow: TextOverflow.ellipsis,
                            ),
                          );
                        }).toList();
                      },
                      child: Container(
                        height: 44,
                        padding: const EdgeInsets.symmetric(horizontal: 11),
                        decoration: BoxDecoration(
                          color: collections.isEmpty
                              ? scheme.surfaceContainerHighest
                              : const Color(0xFFEFF6FF),
                          borderRadius: BorderRadius.circular(12),
                          border: Border.all(
                            color: collections.isEmpty
                                ? theme.dividerColor
                                : const Color(0xFFBFDBFE),
                          ),
                        ),
                        child: Row(
                          mainAxisSize: MainAxisSize.min,
                          children: [
                            Icon(
                              Icons.folder_open_rounded,
                              size: 18,
                              color: collections.isEmpty
                                  ? scheme.onSurfaceVariant
                                  : const Color(0xFF1D4ED8),
                            ),
                            const SizedBox(width: 6),
                            Text(
                              collections.isEmpty ? 'None' : 'Collections',
                              style: theme.textTheme.labelMedium?.copyWith(
                                color: collections.isEmpty
                                    ? scheme.onSurfaceVariant
                                    : const Color(0xFF1D4ED8),
                                fontWeight: FontWeight.w800,
                              ),
                            ),
                          ],
                        ),
                      ),
                    ),
                  ],
                ),
              ],
            ],
          ),
        ),
      ),
    );
  }

  String _shortSession(String value) {
    if (value.length <= 12) {
      return value;
    }
    return '${value.substring(0, 12)}...';
  }
}

class _CompactActionButton extends StatelessWidget {
  const _CompactActionButton({
    required this.icon,
    required this.label,
    required this.onTap,
  });

  final IconData icon;
  final String label;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    return InkWell(
      onTap: onTap,
      borderRadius: BorderRadius.circular(999),
      child: Padding(
        padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 6),
        child: Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(icon, size: 16, color: scheme.primary),
            const SizedBox(width: 5),
            Text(
              label,
              style: Theme.of(context).textTheme.labelMedium?.copyWith(
                color: scheme.primary,
                fontWeight: FontWeight.w800,
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _ErrorBanner extends StatelessWidget {
  const _ErrorBanner({
    required this.message,
    required this.canRetry,
    required this.onRetry,
    required this.onDismiss,
  });

  final String message;
  final bool canRetry;
  final VoidCallback onRetry;
  final VoidCallback onDismiss;

  @override
  Widget build(BuildContext context) {
    return Container(
      width: double.infinity,
      margin: const EdgeInsets.fromLTRB(14, 12, 14, 0),
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: const Color(0xFFFEF2F2),
        borderRadius: BorderRadius.circular(8),
        border: Border.all(color: const Color(0xFFFECACA)),
      ),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Icon(Icons.error_outline_rounded, color: Color(0xFFB91C1C)),
          const SizedBox(width: 10),
          Expanded(
            child: Text(
              message,
              style: Theme.of(
                context,
              ).textTheme.bodyMedium?.copyWith(color: const Color(0xFF7F1D1D)),
            ),
          ),
          if (canRetry)
            TextButton(onPressed: onRetry, child: const Text('Retry')),
          IconButton(
            onPressed: onDismiss,
            icon: const Icon(Icons.close_rounded),
            tooltip: 'Dismiss',
          ),
        ],
      ),
    );
  }
}

class _EmptyState extends StatelessWidget {
  const _EmptyState({required this.hasSession, required this.hasCollections});

  final bool hasSession;
  final bool hasCollections;

  @override
  Widget build(BuildContext context) {
    final title = hasSession
        ? 'Ask a question to start'
        : hasCollections
        ? 'Activate a collection'
        : 'No knowledge-base session yet';
    final body = hasSession
        ? 'Answers will include any Agentic RAG metadata returned by the backend.'
        : hasCollections
        ? 'Use the Collections button above to create a runtime session.'
        : 'Upload a document through /api/v1/upload/document or the web app, then refresh.';

    return LayoutBuilder(
      builder: (context, constraints) {
        return SingleChildScrollView(
          child: ConstrainedBox(
            constraints: BoxConstraints(minHeight: constraints.maxHeight),
            child: Center(
              child: Padding(
                padding: const EdgeInsets.all(28),
                child: Column(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    const Icon(
                      Icons.auto_awesome_rounded,
                      size: 42,
                      color: Color(0xFF2563EB),
                    ),
                    const SizedBox(height: 14),
                    Text(
                      title,
                      textAlign: TextAlign.center,
                      style: Theme.of(context).textTheme.titleMedium?.copyWith(
                        fontWeight: FontWeight.w800,
                        color: const Color(0xFF0F172A),
                      ),
                    ),
                    const SizedBox(height: 8),
                    Text(
                      body,
                      textAlign: TextAlign.center,
                      style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                        color: const Color(0xFF64748B),
                      ),
                    ),
                  ],
                ),
              ),
            ),
          ),
        );
      },
    );
  }
}

class _ChatMessage {
  const _ChatMessage({
    required this.text,
    required this.isUser,
    this.metadata = const {},
    this.sources = const [],
  });

  final String text;
  final bool isUser;
  final Map<String, dynamic> metadata;
  final List<Map<String, dynamic>> sources;

  factory _ChatMessage.user(String text) {
    return _ChatMessage(text: text, isUser: true);
  }

  factory _ChatMessage.assistant(ChatResponse response) {
    return _ChatMessage(
      text: response.answer.isEmpty ? 'No answer generated.' : response.answer,
      isUser: false,
      metadata: response.metadata,
      sources: response.sources,
    );
  }
}
