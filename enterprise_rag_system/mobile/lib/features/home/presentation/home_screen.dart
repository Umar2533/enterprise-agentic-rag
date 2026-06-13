import 'package:flutter/material.dart';

import '../../../core/network/api_client.dart';
import '../../../core/storage/app_session.dart';
import '../../../core/utils/responsive.dart';
import '../../../features/chat/data/models/health_status.dart';
import '../../../features/chat/data/services/chat_api_service.dart';
import '../../../shared/widgets/app_card.dart';
import '../../../shared/widgets/status_badge.dart';

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

  @override
  Widget build(BuildContext context) {
    return SafeArea(
      child: RefreshIndicator(
        onRefresh: _refresh,
        child: ListView(
          padding: const EdgeInsets.all(16),
          children: [
            _HeroHeader(
              online: _health?.isHealthy == true,
              loading: _loading,
              error: _error,
            ),
            const SizedBox(height: 14),
            AppCard(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Row(
                    children: [
                      Expanded(
                        child: Text(
                          'Runtime Status',
                          style: Theme.of(context).textTheme.titleMedium
                              ?.copyWith(fontWeight: FontWeight.w900),
                        ),
                      ),
                      StatusBadge(
                        label: _health?.isHealthy == true
                            ? 'Online'
                            : 'Offline',
                        color: _health?.isHealthy == true
                            ? const Color(0xFF16A34A)
                            : const Color(0xFFDC2626),
                        icon: _health?.isHealthy == true
                            ? Icons.check_circle_rounded
                            : Icons.error_rounded,
                      ),
                    ],
                  ),
                  const SizedBox(height: 12),
                  _StatusLine('Backend', widget.session.backendUrl),
                  _StatusLine(
                    'Vector DB',
                    _health?.vectorDbProvider ?? 'qdrant',
                  ),
                  _StatusLine(
                    'Embedding provider',
                    widget.session.embeddingProvider,
                  ),
                  _StatusLine(
                    'Active collection',
                    widget.session.collectionName.isEmpty
                        ? 'No collection selected'
                        : widget.session.collectionName,
                  ),
                  _StatusLine(
                    'Session',
                    widget.session.sessionId.isEmpty
                        ? 'No active session'
                        : widget.session.sessionId,
                  ),
                ],
              ),
            ),
            const SizedBox(height: 14),
            if (!widget.session.hasSession)
              AppCard(
                child: Row(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    const Icon(
                      Icons.warning_amber_rounded,
                      color: Color(0xFFD97706),
                    ),
                    const SizedBox(width: 10),
                    Expanded(
                      child: Text(
                        'No active knowledge-base session. Upload a document or activate an existing collection before chatting.',
                        style: Theme.of(context).textTheme.bodyMedium,
                      ),
                    ),
                  ],
                ),
              ),
            const SizedBox(height: 14),
            GridView.count(
              shrinkWrap: true,
              physics: const NeverScrollableScrollPhysics(),
              crossAxisCount: Responsive.gridColumns(context),
              crossAxisSpacing: 12,
              mainAxisSpacing: 12,
              childAspectRatio: Responsive.isWide(context) ? 1.7 : 2.8,
              children: [
                _ActionCard(
                  title: 'Upload Document',
                  subtitle: 'Build a new knowledge base',
                  icon: Icons.upload_file_rounded,
                  onTap: () => widget.onNavigate(2),
                ),
                _ActionCard(
                  title: 'Knowledge Base',
                  subtitle: 'Select or inspect collections',
                  icon: Icons.folder_rounded,
                  onTap: () => widget.onNavigate(1),
                ),
                _ActionCard(
                  title: 'Start Chat',
                  subtitle: 'Ask grounded questions',
                  icon: Icons.chat_bubble_rounded,
                  onTap: () => widget.onNavigate(3),
                ),
                _ActionCard(
                  title: 'Settings',
                  subtitle: 'Backend, theme, debug logs',
                  icon: Icons.settings_rounded,
                  onTap: () => widget.onNavigate(4),
                ),
              ],
            ),
          ],
        ),
      ),
    );
  }
}

class _HeroHeader extends StatelessWidget {
  const _HeroHeader({
    required this.online,
    required this.loading,
    required this.error,
  });

  final bool online;
  final bool loading;
  final String? error;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(20),
      decoration: BoxDecoration(
        gradient: const LinearGradient(
          colors: [Color(0xFF0F172A), Color(0xFF2563EB)],
          begin: Alignment.topLeft,
          end: Alignment.bottomRight,
        ),
        borderRadius: BorderRadius.circular(8),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          StatusBadge(
            label: loading
                ? 'Checking'
                : online
                ? 'Backend online'
                : 'Offline',
            color: loading
                ? const Color(0xFFE0F2FE)
                : online
                ? const Color(0xFFBBF7D0)
                : const Color(0xFFFECACA),
            icon: online ? Icons.cloud_done_rounded : Icons.cloud_off_rounded,
          ),
          const SizedBox(height: 18),
          Text(
            'Enterprise Agentic RAG',
            style: Theme.of(context).textTheme.headlineSmall?.copyWith(
              color: Colors.white,
              fontWeight: FontWeight.w900,
            ),
          ),
          const SizedBox(height: 8),
          Text(
            error ??
                'Grounded answers with retrieval, evaluation, and sources.',
            style: Theme.of(
              context,
            ).textTheme.bodyMedium?.copyWith(color: const Color(0xFFE0F2FE)),
          ),
        ],
      ),
    );
  }
}

class _StatusLine extends StatelessWidget {
  const _StatusLine(this.label, this.value);

  final String label;
  final String value;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(top: 8),
      child: Row(
        children: [
          SizedBox(
            width: 130,
            child: Text(
              label,
              style: Theme.of(context).textTheme.bodySmall?.copyWith(
                color: const Color(0xFF64748B),
                fontWeight: FontWeight.w700,
              ),
            ),
          ),
          Expanded(
            child: Text(value, maxLines: 1, overflow: TextOverflow.ellipsis),
          ),
        ],
      ),
    );
  }
}

class _ActionCard extends StatelessWidget {
  const _ActionCard({
    required this.title,
    required this.subtitle,
    required this.icon,
    required this.onTap,
  });

  final String title;
  final String subtitle;
  final IconData icon;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    return AppCard(
      onTap: onTap,
      child: Row(
        children: [
          Container(
            width: 44,
            height: 44,
            decoration: BoxDecoration(
              color: Theme.of(
                context,
              ).colorScheme.primary.withValues(alpha: .1),
              borderRadius: BorderRadius.circular(8),
            ),
            child: Icon(icon, color: Theme.of(context).colorScheme.primary),
          ),
          const SizedBox(width: 12),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              mainAxisAlignment: MainAxisAlignment.center,
              children: [
                Text(
                  title,
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: Theme.of(
                    context,
                  ).textTheme.titleSmall?.copyWith(fontWeight: FontWeight.w900),
                ),
                const SizedBox(height: 4),
                Text(
                  subtitle,
                  maxLines: 2,
                  overflow: TextOverflow.ellipsis,
                  style: Theme.of(context).textTheme.bodySmall?.copyWith(
                    color: const Color(0xFF64748B),
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
