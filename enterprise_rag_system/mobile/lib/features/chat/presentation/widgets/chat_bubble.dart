import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import 'rag_evaluation_card.dart';
import 'source_card.dart';

class ChatBubble extends StatelessWidget {
  const ChatBubble({
    required this.text,
    required this.isUser,
    this.metadata = const {},
    this.sources = const [],
    super.key,
  });

  final String text;
  final bool isUser;
  final Map<String, dynamic> metadata;
  final List<Map<String, dynamic>> sources;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final scheme = theme.colorScheme;
    final width = MediaQuery.sizeOf(context).width;
    final alignment = isUser ? Alignment.centerRight : Alignment.centerLeft;
    final bubbleColor = isUser ? scheme.primary : theme.cardColor;
    final textColor = isUser ? Colors.white : scheme.onSurface;

    return Align(
      alignment: alignment,
      child: ConstrainedBox(
        constraints: BoxConstraints(maxWidth: width < 420 ? width * .9 : 720),
        child: FractionallySizedBox(
          widthFactor: width < 420 ? 1 : .88,
          alignment: alignment,
          child: Column(
            crossAxisAlignment: isUser
                ? CrossAxisAlignment.end
                : CrossAxisAlignment.start,
            children: [
              AnimatedContainer(
                duration: const Duration(milliseconds: 180),
                decoration: BoxDecoration(
                  color: bubbleColor,
                  borderRadius: BorderRadius.only(
                    topLeft: const Radius.circular(18),
                    topRight: const Radius.circular(18),
                    bottomLeft: Radius.circular(isUser ? 18 : 8),
                    bottomRight: Radius.circular(isUser ? 8 : 18),
                  ),
                  border: isUser ? null : Border.all(color: theme.dividerColor),
                  boxShadow: const [
                    BoxShadow(
                      color: Color(0x0D0F172A),
                      blurRadius: 12,
                      offset: Offset(0, 5),
                    ),
                  ],
                ),
                child: Padding(
                  padding: const EdgeInsets.fromLTRB(14, 10, 8, 10),
                  child: Row(
                    crossAxisAlignment: CrossAxisAlignment.end,
                    children: [
                      Expanded(
                        child: Padding(
                          padding: const EdgeInsets.only(right: 6),
                          child: Text(
                            text,
                            style: theme.textTheme.bodyMedium?.copyWith(
                              color: textColor,
                              fontSize: 13.5,
                              height: 1.4,
                              fontWeight: FontWeight.w500,
                            ),
                          ),
                        ),
                      ),
                      _CopyMessageButton(
                        text: text,
                        isUser: isUser,
                        color: isUser
                            ? Colors.white.withValues(alpha: .82)
                            : scheme.onSurfaceVariant,
                      ),
                    ],
                  ),
                ),
              ),
              if (!isUser && (metadata.isNotEmpty || sources.isNotEmpty)) ...[
                const SizedBox(height: 8),
                RagEvaluationCard(
                  metadata: metadata,
                  sourceCount: sources.length,
                ),
                if (sources.isNotEmpty) ...[
                  const SizedBox(height: 8),
                  _SourcesButton(sources: sources),
                ],
              ],
            ],
          ),
        ),
      ),
    );
  }
}

class _CopyMessageButton extends StatelessWidget {
  const _CopyMessageButton({
    required this.text,
    required this.isUser,
    required this.color,
  });

  final String text;
  final bool isUser;
  final Color color;

  @override
  Widget build(BuildContext context) {
    return IconButton(
      onPressed: text.trim().isEmpty ? null : () => _copyText(context),
      icon: const Icon(Icons.copy_rounded, size: 15),
      tooltip: isUser ? 'Copy question' : 'Copy answer',
      visualDensity: VisualDensity.compact,
      constraints: const BoxConstraints.tightFor(width: 24, height: 24),
      padding: const EdgeInsets.all(4.5),
      color: color,
    );
  }

  Future<void> _copyText(BuildContext context) async {
    await Clipboard.setData(ClipboardData(text: text));
    if (!context.mounted) {
      return;
    }
    final messenger = ScaffoldMessenger.of(context);
    messenger.hideCurrentSnackBar();
    messenger.showSnackBar(
      SnackBar(
        content: Text(isUser ? 'Question copied' : 'Answer copied'),
        duration: const Duration(seconds: 2),
      ),
    );
  }
}

class _SourcesButton extends StatelessWidget {
  const _SourcesButton({required this.sources});

  final List<Map<String, dynamic>> sources;

  @override
  Widget build(BuildContext context) {
    return OutlinedButton.icon(
      onPressed: () => _showSources(context),
      icon: const Icon(Icons.menu_book_rounded, size: 17),
      label: Text('Sources (${sources.length})'),
      style: OutlinedButton.styleFrom(
        visualDensity: VisualDensity.compact,
        padding: const EdgeInsets.symmetric(horizontal: 11, vertical: 7),
        textStyle: Theme.of(
          context,
        ).textTheme.labelMedium?.copyWith(fontWeight: FontWeight.w800),
      ),
    );
  }

  Future<void> _showSources(BuildContext context) {
    return showModalBottomSheet<void>(
      context: context,
      isScrollControlled: true,
      useSafeArea: true,
      showDragHandle: true,
      builder: (context) => _SourcesSheet(sources: sources),
    );
  }
}

class _SourcesSheet extends StatelessWidget {
  const _SourcesSheet({required this.sources});

  final List<Map<String, dynamic>> sources;

  @override
  Widget build(BuildContext context) {
    final documents = sources
        .where((source) => !SourceCard.isWebSource(source))
        .toList();
    final webSources = sources.where(SourceCard.isWebSource).toList();

    return DraggableScrollableSheet(
      expand: false,
      initialChildSize: .72,
      minChildSize: .4,
      maxChildSize: .92,
      builder: (context, scrollController) {
        return ListView(
          controller: scrollController,
          padding: const EdgeInsets.fromLTRB(16, 0, 16, 24),
          children: [
            Text(
              'Sources (${sources.length})',
              style: Theme.of(
                context,
              ).textTheme.titleLarge?.copyWith(fontWeight: FontWeight.w900),
            ),
            const SizedBox(height: 4),
            Text(
              'Retrieved context used for this answer.',
              style: Theme.of(context).textTheme.bodySmall?.copyWith(
                color: Theme.of(context).colorScheme.onSurfaceVariant,
              ),
            ),
            if (documents.isNotEmpty) ...[
              const SizedBox(height: 18),
              _SourceGroupHeader(
                icon: Icons.description_outlined,
                label: 'Documents',
                count: documents.length,
              ),
              ...documents.indexed.map(
                (entry) => SourceCard(source: entry.$2, index: entry.$1),
              ),
            ],
            if (webSources.isNotEmpty) ...[
              const SizedBox(height: 18),
              _SourceGroupHeader(
                icon: Icons.language_rounded,
                label: 'Web',
                count: webSources.length,
              ),
              ...webSources.indexed.map(
                (entry) => SourceCard(
                  source: entry.$2,
                  index: documents.length + entry.$1,
                ),
              ),
            ],
          ],
        );
      },
    );
  }
}

class _SourceGroupHeader extends StatelessWidget {
  const _SourceGroupHeader({
    required this.icon,
    required this.label,
    required this.count,
  });

  final IconData icon;
  final String label;
  final int count;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Padding(
      padding: const EdgeInsets.only(bottom: 4),
      child: Row(
        children: [
          Icon(icon, size: 18, color: theme.colorScheme.primary),
          const SizedBox(width: 7),
          Text(
            label,
            style: theme.textTheme.titleSmall?.copyWith(
              fontWeight: FontWeight.w900,
            ),
          ),
          const SizedBox(width: 6),
          Text(
            '$count',
            style: theme.textTheme.labelMedium?.copyWith(
              color: theme.colorScheme.onSurfaceVariant,
            ),
          ),
        ],
      ),
    );
  }
}
