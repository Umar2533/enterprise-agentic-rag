import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../../../core/network/api_client.dart';
import '../../../core/storage/app_session.dart';
import '../../../features/chat/data/models/health_status.dart';
import '../../../features/chat/data/services/chat_api_service.dart';

class HomeScreen extends StatefulWidget {
  const HomeScreen({
    required this.session,
    required this.onNavigate,
    super.key,
  });

  final AppSession session;
  final ValueChanged<int> onNavigate;

  @override
  State<HomeScreen> createState() => _HomeScreenState();
}

class _HomeScreenState extends State<HomeScreen> {
  HealthStatus? _health;
  String? _error;
  bool _loading = true;

  @override
  void initState() {
    super.initState();
    _refresh();
  }

  Future<void> _refresh() async {
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final service = ChatApiService(
        baseUrl: widget.session.backendUrl,
        apiClient: ApiClient(debugMode: widget.session.debugMode),
      );
      final health = await service.checkHealth();
      if (mounted) {
        setState(() {
          _health = health;
          _loading = false;
        });
      }
    } catch (error) {
      if (mounted) {
        setState(() {
          _error = error.toString();
          _loading = false;
        });
      }
    }
  }

  String get _backendLabel {
    if (_loading) return 'Checking';
    if (_health?.isHealthy == true) return 'Online';
    if (_health != null && _error == null) return 'Degraded';
    return 'Offline';
  }

  Color get _backendColor {
    if (_loading) return _HomePalette.cyan;
    if (_health?.isHealthy == true) return _HomePalette.green;
    if (_health != null && _error == null) return _HomePalette.amber;
    return _HomePalette.red;
  }

  IconData get _backendIcon {
    if (_loading) return Icons.sync_rounded;
    if (_health?.isHealthy == true) return Icons.check_circle_rounded;
    return Icons.error_outline_rounded;
  }

  @override
  Widget build(BuildContext context) {
    return AnnotatedRegion<SystemUiOverlayStyle>(
      value: const SystemUiOverlayStyle(
        statusBarColor: _HomePalette.background,
        statusBarIconBrightness: Brightness.light,
        systemNavigationBarColor: _HomePalette.background,
        systemNavigationBarIconBrightness: Brightness.light,
      ),
      child: ColoredBox(
        color: _HomePalette.background,
        child: SafeArea(
          child: RefreshIndicator(
            onRefresh: _refresh,
            color: _HomePalette.cyan,
            backgroundColor: _HomePalette.card,
            child: LayoutBuilder(
              builder: (context, constraints) {
                return ListView(
                  padding: const EdgeInsets.fromLTRB(14, 10, 14, 16),
                  children: [
                    _HeroCard(
                      label: _backendLabel,
                      color: _backendColor,
                      icon: _backendIcon,
                      hasError: _error != null,
                    ),
                    const SizedBox(height: 10),
                    _StatsRow(
                      openAiActive: widget.session.hasActiveOpenAiKey,
                      hasCollection: widget.session.hasCollection,
                      backendLabel: _backendLabel,
                      backendColor: _backendColor,
                    ),
                    const SizedBox(height: 10),
                    _RuntimeCard(
                      statusLabel: _backendLabel,
                      statusColor: _backendColor,
                      statusIcon: _backendIcon,
                      backendUrl: widget.session.backendUrl,
                      vectorDb: _health?.vectorDbProvider ?? 'Unavailable',
                      embeddings: widget.session.embeddingProvider,
                      collection: widget.session.collectionName,
                      sessionId: widget.session.sessionId,
                    ),
                    const SizedBox(height: 10),
                    const _SectionLabel('QUICK ACTIONS'),
                    const SizedBox(height: 7),
                    GridView.count(
                      shrinkWrap: true,
                      physics: const NeverScrollableScrollPhysics(),
                      crossAxisCount: 2,
                      crossAxisSpacing: 9,
                      mainAxisSpacing: 9,
                      childAspectRatio: constraints.maxWidth < 330 ? 1.18 : 1.3,
                      children: [
                        _ActionCard(
                          title: 'Upload Doc',
                          subtitle: 'Build a knowledge base',
                          icon: Icons.description_rounded,
                          accent: const Color(0xFF7C6DFF),
                          onTap: () => widget.onNavigate(2),
                        ),
                        _ActionCard(
                          title: 'Knowledge',
                          subtitle: 'Inspect collections',
                          icon: Icons.folder_rounded,
                          accent: _HomePalette.cyan,
                          onTap: () => widget.onNavigate(1),
                        ),
                        _ActionCard(
                          title: 'Chat',
                          subtitle: 'Ask grounded questions',
                          icon: Icons.chat_bubble_rounded,
                          accent: const Color(0xFFD1A93A),
                          onTap: () => widget.onNavigate(3),
                        ),
                        _ActionCard(
                          title: 'Settings',
                          subtitle: 'Configure runtime',
                          icon: Icons.settings_rounded,
                          accent: const Color(0xFFB95D85),
                          onTap: () => widget.onNavigate(4),
                        ),
                      ],
                    ),
                    const SizedBox(height: 10),
                    _RecentActivityCard(
                      collectionName: widget.session.collectionName,
                      sessionId: widget.session.sessionId,
                      error: _error,
                    ),
                  ],
                );
              },
            ),
          ),
        ),
      ),
    );
  }
}

class _HomePalette {
  const _HomePalette._();

  static const background = Color(0xFF060A12);
  static const card = Color(0xFF0D1421);
  static const border = Color(0xFF202C3E);
  static const text = Color(0xFFF5F7FF);
  static const muted = Color(0xFF7F91AD);
  static const cyan = Color(0xFF18D7F2);
  static const purple = Color(0xFF766BFF);
  static const green = Color(0xFF35D69A);
  static const amber = Color(0xFFF0B84B);
  static const red = Color(0xFFFF5D72);
}

class _HeroCard extends StatelessWidget {
  const _HeroCard({
    required this.label,
    required this.color,
    required this.icon,
    required this.hasError,
  });

  final String label;
  final Color color;
  final IconData icon;
  final bool hasError;

  @override
  Widget build(BuildContext context) {
    return ClipRRect(
      borderRadius: BorderRadius.circular(20),
      child: Stack(
        children: [
          const Positioned.fill(
            child: DecoratedBox(
              decoration: BoxDecoration(
                gradient: LinearGradient(
                  colors: [Color(0xFF242760), Color(0xFF0F5871)],
                  begin: Alignment.topLeft,
                  end: Alignment.bottomRight,
                ),
              ),
            ),
          ),
          const Positioned(
            top: -68,
            right: -38,
            child: _AuroraGlow(size: 176, color: Color(0xFF536DFF)),
          ),
          const Positioned(
            bottom: -92,
            left: 58,
            child: _AuroraGlow(size: 190, color: Color(0xFF00D7E8)),
          ),
          Padding(
            padding: const EdgeInsets.fromLTRB(17, 16, 17, 18),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                _Pill(label: label, color: color, icon: icon, compact: true),
                const SizedBox(height: 13),
                RichText(
                  text: const TextSpan(
                    style: TextStyle(
                      color: _HomePalette.text,
                      fontSize: 21,
                      height: 1.03,
                      fontWeight: FontWeight.w900,
                    ),
                    children: [
                      TextSpan(text: 'Enterprise\n'),
                      TextSpan(
                        text: 'Agentic RAG',
                        style: TextStyle(color: _HomePalette.cyan),
                      ),
                    ],
                  ),
                ),
                const SizedBox(height: 9),
                Text(
                  hasError
                      ? 'Backend unavailable. Pull down to check again.'
                      : 'Grounded answers with retrieval, evaluation, and cited sources.',
                  style: const TextStyle(
                    color: Color(0xFFB9C8DE),
                    fontSize: 12.5,
                    height: 1.45,
                  ),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}

class _AuroraGlow extends StatelessWidget {
  const _AuroraGlow({required this.size, required this.color});

  final double size;
  final Color color;

  @override
  Widget build(BuildContext context) {
    return Container(
      width: size,
      height: size,
      decoration: BoxDecoration(
        shape: BoxShape.circle,
        gradient: RadialGradient(
          colors: [color.withValues(alpha: .34), color.withValues(alpha: 0)],
        ),
      ),
    );
  }
}

class _StatsRow extends StatelessWidget {
  const _StatsRow({
    required this.openAiActive,
    required this.hasCollection,
    required this.backendLabel,
    required this.backendColor,
  });

  final bool openAiActive;
  final bool hasCollection;
  final String backendLabel;
  final Color backendColor;

  @override
  Widget build(BuildContext context) {
    return Row(
      children: [
        Expanded(
          child: _StatCard(
            value: openAiActive ? 'Active' : 'Missing',
            label: 'OPENAI',
            color: openAiActive ? _HomePalette.cyan : _HomePalette.amber,
          ),
        ),
        const SizedBox(width: 8),
        Expanded(
          child: _StatCard(
            value: hasCollection ? 'Selected' : 'None',
            label: 'COLLECTION',
            color: hasCollection ? _HomePalette.purple : _HomePalette.muted,
          ),
        ),
        const SizedBox(width: 8),
        Expanded(
          child: _StatCard(
            value: backendLabel,
            label: 'STATUS',
            color: backendColor,
          ),
        ),
      ],
    );
  }
}

class _StatCard extends StatelessWidget {
  const _StatCard({
    required this.value,
    required this.label,
    required this.color,
  });

  final String value;
  final String label;
  final Color color;

  @override
  Widget build(BuildContext context) {
    return Container(
      height: 66,
      padding: const EdgeInsets.symmetric(horizontal: 7, vertical: 9),
      decoration: BoxDecoration(
        color: _HomePalette.card,
        borderRadius: BorderRadius.circular(14),
        border: Border.all(color: _HomePalette.border),
      ),
      child: Column(
        mainAxisAlignment: MainAxisAlignment.center,
        children: [
          Text(
            value,
            maxLines: 1,
            overflow: TextOverflow.ellipsis,
            textAlign: TextAlign.center,
            style: TextStyle(
              color: color,
              fontSize: 13,
              fontWeight: FontWeight.w900,
            ),
          ),
          const SizedBox(height: 5),
          Text(
            label,
            maxLines: 1,
            overflow: TextOverflow.ellipsis,
            style: const TextStyle(
              color: _HomePalette.muted,
              fontSize: 8.5,
              letterSpacing: .8,
              fontWeight: FontWeight.w700,
            ),
          ),
        ],
      ),
    );
  }
}

class _RuntimeCard extends StatelessWidget {
  const _RuntimeCard({
    required this.statusLabel,
    required this.statusColor,
    required this.statusIcon,
    required this.backendUrl,
    required this.vectorDb,
    required this.embeddings,
    required this.collection,
    required this.sessionId,
  });

  final String statusLabel;
  final Color statusColor;
  final IconData statusIcon;
  final String backendUrl;
  final String vectorDb;
  final String embeddings;
  final String collection;
  final String sessionId;

  @override
  Widget build(BuildContext context) {
    return _Panel(
      padding: const EdgeInsets.fromLTRB(13, 12, 13, 10),
      child: Column(
        children: [
          Row(
            children: [
              const Expanded(child: _CardTitle('Runtime Status')),
              _Pill(
                label: statusLabel,
                color: statusColor,
                icon: statusIcon,
                compact: true,
              ),
            ],
          ),
          const SizedBox(height: 9),
          _RuntimeRow(label: 'BACKEND', value: backendUrl),
          _RuntimeRow(
            label: 'VECTOR DB',
            value: vectorDb,
            valueColor: _HomePalette.cyan,
          ),
          _RuntimeRow(
            label: 'EMBEDDINGS',
            value: embeddings,
            valueColor: _HomePalette.text,
          ),
          _RuntimeRow(
            label: 'COLLECTION',
            value: collection.isEmpty ? 'Not selected' : collection,
          ),
          _RuntimeRow(
            label: 'SESSION',
            value: sessionId.isEmpty ? 'Not active' : sessionId,
            showDivider: false,
          ),
        ],
      ),
    );
  }
}

class _RuntimeRow extends StatelessWidget {
  const _RuntimeRow({
    required this.label,
    required this.value,
    this.valueColor = _HomePalette.text,
    this.showDivider = true,
  });

  final String label;
  final String value;
  final Color valueColor;
  final bool showDivider;

  @override
  Widget build(BuildContext context) {
    return Container(
      height: 37,
      decoration: BoxDecoration(
        border: showDivider
            ? const Border(bottom: BorderSide(color: _HomePalette.border))
            : null,
      ),
      child: Row(
        children: [
          const SizedBox(width: 1),
          SizedBox(
            width: 91,
            child: Text(
              label,
              style: const TextStyle(
                color: _HomePalette.muted,
                fontSize: 9.5,
                letterSpacing: .75,
                fontWeight: FontWeight.w600,
              ),
            ),
          ),
          Expanded(
            child: Tooltip(
              message: value,
              child: Text(
                value,
                maxLines: 1,
                overflow: TextOverflow.ellipsis,
                textAlign: TextAlign.end,
                style: TextStyle(
                  color: valueColor,
                  fontSize: 10.5,
                  fontWeight: FontWeight.w800,
                ),
              ),
            ),
          ),
        ],
      ),
    );
  }
}

class _SectionLabel extends StatelessWidget {
  const _SectionLabel(this.label);

  final String label;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(left: 2),
      child: Text(
        label,
        style: const TextStyle(
          color: _HomePalette.muted,
          fontSize: 9.5,
          letterSpacing: .75,
          fontWeight: FontWeight.w700,
        ),
      ),
    );
  }
}

class _ActionCard extends StatelessWidget {
  const _ActionCard({
    required this.title,
    required this.subtitle,
    required this.icon,
    required this.accent,
    required this.onTap,
  });

  final String title;
  final String subtitle;
  final IconData icon;
  final Color accent;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    return Material(
      color: _HomePalette.card,
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(15),
        side: BorderSide(color: accent.withValues(alpha: .38)),
      ),
      clipBehavior: Clip.antiAlias,
      child: InkWell(
        onTap: onTap,
        splashColor: accent.withValues(alpha: .12),
        highlightColor: accent.withValues(alpha: .07),
        child: Padding(
          padding: const EdgeInsets.all(12),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Container(
                width: 34,
                height: 34,
                decoration: BoxDecoration(
                  color: accent.withValues(alpha: .18),
                  borderRadius: BorderRadius.circular(9),
                ),
                child: Icon(icon, size: 18, color: accent),
              ),
              const Spacer(),
              Text(
                title,
                maxLines: 1,
                overflow: TextOverflow.ellipsis,
                style: const TextStyle(
                  color: _HomePalette.text,
                  fontSize: 12,
                  fontWeight: FontWeight.w900,
                ),
              ),
              const SizedBox(height: 2),
              Text(
                subtitle,
                maxLines: 1,
                overflow: TextOverflow.ellipsis,
                style: const TextStyle(
                  color: _HomePalette.muted,
                  fontSize: 9.5,
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class _RecentActivityCard extends StatelessWidget {
  const _RecentActivityCard({
    required this.collectionName,
    required this.sessionId,
    required this.error,
  });

  final String collectionName;
  final String sessionId;
  final String? error;

  @override
  Widget build(BuildContext context) {
    final hasCollection = collectionName.trim().isNotEmpty;
    final hasSession = sessionId.trim().isNotEmpty;
    return _Panel(
      padding: const EdgeInsets.fromLTRB(13, 12, 13, 11),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const _CardTitle('Recent Activity'),
          const SizedBox(height: 8),
          if (error != null)
            const _ActivityRow(
              title: 'Connection check failed',
              detail: 'Pull down to retry',
              badge: 'Error',
              color: _HomePalette.red,
            ),
          if (hasCollection)
            _ActivityRow(
              title: collectionName,
              detail: 'Active collection',
              badge: 'Selected',
              color: _HomePalette.cyan,
            ),
          if (hasSession)
            _ActivityRow(
              title: sessionId,
              detail: 'Current session',
              badge: 'Active',
              color: _HomePalette.green,
            ),
          if (error == null && !hasCollection && !hasSession)
            const Padding(
              padding: EdgeInsets.symmetric(vertical: 8),
              child: Row(
                children: [
                  Icon(
                    Icons.history_rounded,
                    size: 18,
                    color: _HomePalette.muted,
                  ),
                  SizedBox(width: 9),
                  Expanded(
                    child: Text(
                      'No recent activity yet.',
                      style: TextStyle(color: _HomePalette.muted, fontSize: 11),
                    ),
                  ),
                ],
              ),
            ),
        ],
      ),
    );
  }
}

class _ActivityRow extends StatelessWidget {
  const _ActivityRow({
    required this.title,
    required this.detail,
    required this.badge,
    required this.color,
  });

  final String title;
  final String detail;
  final String badge;
  final Color color;

  @override
  Widget build(BuildContext context) {
    return Container(
      constraints: const BoxConstraints(minHeight: 43),
      padding: const EdgeInsets.symmetric(vertical: 6),
      decoration: const BoxDecoration(
        border: Border(bottom: BorderSide(color: _HomePalette.border)),
      ),
      child: Row(
        children: [
          Container(
            width: 6,
            height: 6,
            decoration: BoxDecoration(color: color, shape: BoxShape.circle),
          ),
          const SizedBox(width: 9),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              mainAxisAlignment: MainAxisAlignment.center,
              children: [
                Text(
                  title,
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: const TextStyle(
                    color: _HomePalette.text,
                    fontSize: 10.5,
                    fontWeight: FontWeight.w800,
                  ),
                ),
                const SizedBox(height: 1),
                Text(
                  detail,
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: const TextStyle(
                    color: _HomePalette.muted,
                    fontSize: 8.5,
                  ),
                ),
              ],
            ),
          ),
          const SizedBox(width: 8),
          _Pill(label: badge, color: color, compact: true),
        ],
      ),
    );
  }
}

class _Panel extends StatelessWidget {
  const _Panel({required this.child, required this.padding});

  final Widget child;
  final EdgeInsetsGeometry padding;

  @override
  Widget build(BuildContext context) {
    return Container(
      width: double.infinity,
      padding: padding,
      decoration: BoxDecoration(
        color: _HomePalette.card,
        borderRadius: BorderRadius.circular(17),
        border: Border.all(color: _HomePalette.border),
      ),
      child: child,
    );
  }
}

class _CardTitle extends StatelessWidget {
  const _CardTitle(this.title);

  final String title;

  @override
  Widget build(BuildContext context) {
    return Text(
      title,
      style: const TextStyle(
        color: _HomePalette.text,
        fontSize: 12,
        fontWeight: FontWeight.w900,
      ),
    );
  }
}

class _Pill extends StatelessWidget {
  const _Pill({
    required this.label,
    required this.color,
    this.icon,
    this.compact = false,
  });

  final String label;
  final Color color;
  final IconData? icon;
  final bool compact;

  @override
  Widget build(BuildContext context) {
    return Container(
      constraints: const BoxConstraints(maxWidth: 145),
      padding: EdgeInsets.symmetric(
        horizontal: compact ? 7 : 9,
        vertical: compact ? 3 : 5,
      ),
      decoration: BoxDecoration(
        color: color.withValues(alpha: .12),
        borderRadius: BorderRadius.circular(999),
        border: Border.all(color: color.withValues(alpha: .4)),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          if (icon != null) ...[
            Icon(icon, size: compact ? 10 : 13, color: color),
            const SizedBox(width: 4),
          ],
          Flexible(
            child: Text(
              label,
              maxLines: 1,
              overflow: TextOverflow.ellipsis,
              style: TextStyle(
                color: color,
                fontSize: compact ? 8.5 : 10,
                fontWeight: FontWeight.w800,
              ),
            ),
          ),
        ],
      ),
    );
  }
}
