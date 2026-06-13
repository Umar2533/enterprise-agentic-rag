import 'package:flutter/material.dart';

class SourceCard extends StatelessWidget {
  const SourceCard({required this.source, required this.index, super.key});

  final Map<String, dynamic> source;
  final int index;

  static bool isWebSource(Map<String, dynamic> source) {
    final metadata = source['metadata'] is Map
        ? Map<String, dynamic>.from(source['metadata'] as Map)
        : const <String, dynamic>{};
    final markers = [
      source['source_kind'],
      source['source_type'],
      source['retrieval_type'],
      source['type'],
      source['source'],
      metadata['source_type'],
      metadata['retrieval_type'],
      metadata['source'],
    ];
    return markers.any(
          (value) => value?.toString().toLowerCase().contains('web') == true,
        ) ||
        _value(source, metadata, const ['url', 'link']) != null;
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final scheme = theme.colorScheme;
    final metadata = source['metadata'] is Map
        ? Map<String, dynamic>.from(source['metadata'] as Map)
        : <String, dynamic>{};
    final isWeb = isWebSource(source);
    final title = isWeb
        ? _value(source, metadata, const ['title', 'url', 'source'])
        : _value(source, metadata, const [
            'file_name',
            'filename',
            'document_title',
            'source',
          ]);
    final preview = _value(source, metadata, const [
      'page_content',
      'content',
      'preview',
      'snippet',
      'summary',
    ]);
    final url = _value(source, metadata, const ['url', 'link']);
    final page = _value(source, metadata, const ['page_number', 'page']);
    final chunk = _value(source, metadata, const ['chunk_id', 'chunk_index']);
    final section = _value(source, metadata, const ['section_title']);
    final collection = _value(source, metadata, const ['collection_name']);
    final retrievalType = _value(source, metadata, const ['retrieval_type']);
    final score = _value(source, metadata, const [
      'retrieval_score',
      'score',
    ]);
    final details = [
      if (isWeb) 'Web',
      if (!isWeb && page != null) 'p. $page',
      if (!isWeb && chunk != null) 'chunk $chunk',
      if (_formatScore(score) case final value?) 'score $value',
    ].join('  ');
    final metadataItems = <_SourceMetadata>[
      _metadataItem('Page', isWeb ? null : page),
      _metadataItem('Chunk', isWeb ? null : chunk),
      _metadataItem('Section', section),
      _metadataItem('Collection', collection),
      _metadataItem('Retrieval', retrievalType),
      _metadataItem('Score', _formatScore(score)),
      _metadataItem(
        'Dense',
        _formatScore(_value(source, metadata, const ['dense_score'])),
      ),
      _metadataItem(
        'BM25',
        _formatScore(_value(source, metadata, const ['bm25_score'])),
      ),
      _metadataItem(
        'Metadata',
        _formatScore(_value(source, metadata, const ['metadata_score'])),
      ),
      _metadataItem(
        'Keyword',
        _formatScore(_value(source, metadata, const ['keyword_score'])),
      ),
    ].where((item) => item.value.isNotEmpty).toList();

    return Container(
      margin: const EdgeInsets.only(top: 6),
      decoration: BoxDecoration(
        color: scheme.surface,
        borderRadius: BorderRadius.circular(14),
        border: Border.all(color: theme.dividerColor),
      ),
      child: ExpansionTile(
        tilePadding: const EdgeInsets.fromLTRB(12, 0, 8, 0),
        childrenPadding: const EdgeInsets.fromLTRB(12, 0, 12, 12),
        dense: true,
        shape: const RoundedRectangleBorder(),
        collapsedShape: const RoundedRectangleBorder(),
        leading: Container(
          width: 28,
          height: 28,
          alignment: Alignment.center,
          decoration: BoxDecoration(
            color: scheme.primary.withValues(alpha: .1),
            borderRadius: BorderRadius.circular(9),
          ),
          child: Text(
            isWeb ? 'W${index + 1}' : '${index + 1}',
            style: theme.textTheme.labelMedium?.copyWith(
              color: scheme.primary,
              fontWeight: FontWeight.w900,
            ),
          ),
        ),
        title: Text(
          title?.toString() ?? '${isWeb ? 'Web source' : 'Document'} ${index + 1}',
          maxLines: 1,
          overflow: TextOverflow.ellipsis,
          style: theme.textTheme.labelMedium?.copyWith(
            fontWeight: FontWeight.w900,
            color: scheme.onSurface,
          ),
        ),
        subtitle: details.isEmpty
            ? null
            : Text(
                details,
                maxLines: 1,
                overflow: TextOverflow.ellipsis,
                style: theme.textTheme.bodySmall?.copyWith(
                  color: scheme.onSurfaceVariant,
                  fontSize: 11.5,
                ),
              ),
        children: [
          if (url != null && url.toString().trim().isNotEmpty) ...[
            Align(
              alignment: Alignment.centerLeft,
              child: SelectableText(
                url.toString(),
                style: theme.textTheme.bodySmall?.copyWith(
                  color: scheme.primary,
                  fontWeight: FontWeight.w600,
                ),
              ),
            ),
            const SizedBox(height: 8),
          ],
          if (metadataItems.isNotEmpty) ...[
            Align(
              alignment: Alignment.centerLeft,
              child: Wrap(
                spacing: 6,
                runSpacing: 6,
                children: metadataItems
                    .map((item) => _SourceMetadataChip(item: item))
                    .toList(),
              ),
            ),
            const SizedBox(height: 10),
          ],
          if (preview != null && preview.toString().trim().isNotEmpty)
            Text(
              preview.toString(),
              maxLines: 8,
              overflow: TextOverflow.ellipsis,
              style: theme.textTheme.bodySmall?.copyWith(height: 1.4),
            ),
        ],
      ),
    );
  }

  String? _formatScore(Object? value) {
    if (value == null) {
      return null;
    }
    if (value is num) {
      return value.toStringAsFixed(value.abs() >= 10 ? 1 : 3);
    }
    final parsed = num.tryParse(value.toString());
    if (parsed == null) {
      return value.toString();
    }
    return parsed.toStringAsFixed(parsed.abs() >= 10 ? 1 : 3);
  }

  _SourceMetadata _metadataItem(String label, Object? value) {
    return _SourceMetadata(label, value?.toString().trim() ?? '');
  }

  static Object? _value(
    Map<String, dynamic> source,
    Map<String, dynamic> metadata,
    List<String> keys,
  ) {
    for (final key in keys) {
      final direct = source[key];
      if (direct != null && direct.toString().trim().isNotEmpty) {
        return direct;
      }
      final nested = metadata[key];
      if (nested != null && nested.toString().trim().isNotEmpty) {
        return nested;
      }
    }
    return null;
  }
}

class _SourceMetadataChip extends StatelessWidget {
  const _SourceMetadataChip({required this.item});

  final _SourceMetadata item;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 5),
      decoration: BoxDecoration(
        color: theme.colorScheme.surfaceContainerHighest.withValues(alpha: .5),
        borderRadius: BorderRadius.circular(999),
        border: Border.all(color: theme.dividerColor),
      ),
      child: Text(
        '${item.label}: ${item.value}',
        style: theme.textTheme.bodySmall?.copyWith(fontSize: 11),
      ),
    );
  }
}

class _SourceMetadata {
  const _SourceMetadata(this.label, this.value);

  final String label;
  final String value;
}
