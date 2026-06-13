import 'package:flutter/material.dart';

class RagEvaluationCard extends StatelessWidget {
  const RagEvaluationCard({
    required this.metadata,
    required this.sourceCount,
    super.key,
  });

  final Map<String, dynamic> metadata;
  final int sourceCount;

  @override
  Widget build(BuildContext context) {
    final chips = <_MetadataItem>[
      _item(
        'Confidence',
        metadata['confidence_level'] ?? metadata['confidence'],
      ),
      _item(
        'Evaluation',
        metadata['evaluation'] ?? metadata['evaluation_status'],
      ),
      _item('Mode', _friendlyRetrievalMode(metadata['retrieval_mode'])),
      _item(
        'Iterations',
        metadata['iteration_count'] ?? metadata['iterations'],
      ),
      _item(
        'Sources',
        sourceCount > 0 ? sourceCount : null,
      ),
      _item(
        'Web',
        metadata['web_search_used'] == true ? 'used' : null,
      ),
    ].where((item) => item.value.isNotEmpty).toList();

    if (chips.isEmpty) {
      return const SizedBox.shrink();
    }

    return Wrap(
      spacing: 6,
      runSpacing: 6,
      children: chips
          .map(
            (item) => _MetadataChip(label: item.label, value: item.value),
          )
          .toList(),
    );
  }

  _MetadataItem _item(String label, Object? value) {
    if (value == null) {
      return _MetadataItem(label, '');
    }
    if (value is String && value.trim().isEmpty) {
      return _MetadataItem(label, '');
    }
    if (value is Iterable && value.isEmpty) {
      return _MetadataItem(label, '');
    }
    return _MetadataItem(label, value.toString());
  }

  String? _friendlyRetrievalMode(Object? value) {
    final mode = value?.toString().trim().toLowerCase() ?? '';
    if (mode.isEmpty || mode == 'unknown') {
      return null;
    }
    if (mode.contains('hybrid')) {
      return 'Hybrid';
    }
    if (mode.contains('dense')) {
      return 'Document search';
    }
    if (mode.contains('web')) {
      return 'Web';
    }
    return null;
  }
}

class _MetadataChip extends StatelessWidget {
  const _MetadataChip({required this.label, required this.value});

  final String label;
  final String value;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 5),
      decoration: BoxDecoration(
        color: Theme.of(context).colorScheme.surfaceContainerHighest.withValues(
          alpha: .55,
        ),
        borderRadius: BorderRadius.circular(999),
        border: Border.all(color: Theme.of(context).dividerColor),
      ),
      child: RichText(
        maxLines: 1,
        overflow: TextOverflow.ellipsis,
        text: TextSpan(
          style: Theme.of(context).textTheme.bodySmall?.copyWith(height: 1.15),
          children: [
            TextSpan(
              text: '$label: ',
              style: const TextStyle(fontWeight: FontWeight.w800),
            ),
            TextSpan(text: value),
          ],
        ),
      ),
    );
  }
}

class _MetadataItem {
  const _MetadataItem(this.label, this.value);

  final String label;
  final String value;
}
