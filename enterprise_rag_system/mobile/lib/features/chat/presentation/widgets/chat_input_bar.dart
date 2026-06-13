import 'package:flutter/material.dart';

class ChatInputBar extends StatefulWidget {
  const ChatInputBar({
    required this.onSend,
    required this.enabled,
    required this.webSearchEnabled,
    required this.onWebSearchChanged,
    super.key,
  });

  final ValueChanged<String> onSend;
  final bool enabled;
  final bool webSearchEnabled;
  final ValueChanged<bool> onWebSearchChanged;

  @override
  State<ChatInputBar> createState() => _ChatInputBarState();
}

class _ChatInputBarState extends State<ChatInputBar> {
  final TextEditingController _controller = TextEditingController();

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  void _submit() {
    final text = _controller.text.trim();
    if (text.isEmpty || !widget.enabled) {
      return;
    }
    _controller.clear();
    widget.onSend(text);
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final scheme = theme.colorScheme;
    final mediaQuery = MediaQuery.of(context);
    final availableHeight =
        mediaQuery.size.height - mediaQuery.viewInsets.bottom;
    final compact =
        mediaQuery.orientation == Orientation.landscape ||
        availableHeight < 420;
    return Container(
      decoration: BoxDecoration(
        color: scheme.surface,
        border: Border(top: BorderSide(color: theme.dividerColor)),
        boxShadow: const [
          BoxShadow(
            color: Color(0x0F0F172A),
            blurRadius: 16,
            offset: Offset(0, -4),
          ),
        ],
      ),
      child: Padding(
        padding: compact
            ? const EdgeInsets.fromLTRB(8, 2, 8, 3)
            : const EdgeInsets.fromLTRB(12, 6, 12, 7),
        child: Container(
          decoration: BoxDecoration(
            color: scheme.surfaceContainerHighest.withValues(
              alpha: theme.brightness == Brightness.dark ? .45 : .72,
            ),
            borderRadius: BorderRadius.circular(18),
            border: Border.all(color: theme.dividerColor),
          ),
          child: Row(
            crossAxisAlignment: CrossAxisAlignment.end,
            children: [
              Padding(
                padding: compact
                    ? const EdgeInsets.fromLTRB(5, 3, 1, 3)
                    : const EdgeInsets.fromLTRB(7, 7, 2, 7),
                child: Tooltip(
                  message: widget.webSearchEnabled
                      ? 'Web search on'
                      : 'Web search off',
                  child: Semantics(
                    button: true,
                    enabled: widget.enabled,
                    toggled: widget.webSearchEnabled,
                    label: 'Web search',
                    child: InkResponse(
                      onTap: widget.enabled
                          ? () => widget.onWebSearchChanged(
                              !widget.webSearchEnabled,
                            )
                          : null,
                      radius: 20,
                      child: AnimatedContainer(
                        duration: const Duration(milliseconds: 140),
                        width: compact ? 28 : 34,
                        height: compact ? 28 : 34,
                        decoration: BoxDecoration(
                          color: !widget.enabled
                              ? scheme.surfaceContainerHighest.withValues(
                                  alpha: .5,
                                )
                              : widget.webSearchEnabled
                              ? const Color(0xFFDCFCE7)
                              : scheme.surface.withValues(alpha: .58),
                          shape: BoxShape.circle,
                          border: Border.all(
                            color: !widget.enabled
                                ? theme.dividerColor.withValues(alpha: .55)
                                : widget.webSearchEnabled
                                ? const Color(0xFF86EFAC)
                                : theme.dividerColor,
                          ),
                        ),
                        child: Icon(
                          Icons.language_rounded,
                          size: compact ? 15 : 17,
                          color: !widget.enabled
                              ? scheme.onSurfaceVariant.withValues(alpha: .4)
                              : widget.webSearchEnabled
                              ? const Color(0xFF15803D)
                              : scheme.onSurfaceVariant,
                        ),
                      ),
                    ),
                  ),
                ),
              ),
              Expanded(
                child: TextField(
                  controller: _controller,
                  enabled: widget.enabled,
                  minLines: 1,
                  maxLines: compact ? 1 : 4,
                  textCapitalization: TextCapitalization.sentences,
                  textInputAction: TextInputAction.send,
                  onSubmitted: (_) => _submit(),
                  decoration: InputDecoration(
                    filled: false,
                    border: InputBorder.none,
                    enabledBorder: InputBorder.none,
                    focusedBorder: InputBorder.none,
                    disabledBorder: InputBorder.none,
                    hintText: widget.enabled
                        ? 'Ask your knowledge base'
                        : 'Activate a session to chat',
                    hintStyle: TextStyle(
                      color: scheme.onSurfaceVariant.withValues(alpha: .82),
                    ),
                    contentPadding: compact
                        ? const EdgeInsets.fromLTRB(10, 7, 6, 7)
                        : const EdgeInsets.fromLTRB(15, 11, 10, 11),
                  ),
                  style: TextStyle(
                    color: scheme.onSurface,
                    fontSize: 14,
                    height: 1.35,
                    fontWeight: FontWeight.w500,
                  ),
                  cursorColor: scheme.primary,
                ),
              ),
              Padding(
                padding: compact
                    ? const EdgeInsets.fromLTRB(0, 2, 4, 2)
                    : const EdgeInsets.fromLTRB(0, 5, 6, 5),
                child: AnimatedScale(
                  duration: const Duration(milliseconds: 120),
                  scale: widget.enabled ? 1 : .96,
                  child: IconButton.filled(
                    onPressed: widget.enabled ? _submit : null,
                    icon: Icon(
                      Icons.arrow_upward_rounded,
                      size: compact ? 18 : 20,
                    ),
                    tooltip: 'Send',
                    style: IconButton.styleFrom(
                      backgroundColor: scheme.primary,
                      foregroundColor: Colors.white,
                      disabledBackgroundColor: scheme.surfaceContainerHighest,
                      disabledForegroundColor: scheme.onSurfaceVariant,
                      fixedSize: compact
                          ? const Size(34, 34)
                          : const Size(40, 40),
                      shape: RoundedRectangleBorder(
                        borderRadius: BorderRadius.circular(13),
                      ),
                    ),
                  ),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}
