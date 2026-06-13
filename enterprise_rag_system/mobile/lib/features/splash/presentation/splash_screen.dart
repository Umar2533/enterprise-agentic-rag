import 'package:flutter/material.dart';

import '../../../core/network/api_client.dart';
import '../../../core/storage/app_session.dart';
import '../../../features/chat/data/models/health_status.dart';
import '../../../features/chat/data/services/chat_api_service.dart';
import '../../../shared/widgets/error_view.dart';

class SplashScreen extends StatefulWidget {
  const SplashScreen({required this.session, required this.onReady, super.key});

  final AppSession session;
  final ValueChanged<BuildContext> onReady;

  @override
  State<SplashScreen> createState() => _SplashScreenState();
}

class _SplashScreenState extends State<SplashScreen>
    with SingleTickerProviderStateMixin {
  late final AnimationController _controller;
  String? _error;
  HealthStatus? _health;
  bool _checking = true;

  @override
  void initState() {
    super.initState();
    _controller = AnimationController(
      vsync: this,
      duration: const Duration(milliseconds: 900),
    )..forward();
    _checkHealth();
  }

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  Future<void> _checkHealth() async {
    setState(() {
      _checking = true;
      _error = null;
    });
    try {
      final service = ChatApiService(
        baseUrl: widget.session.backendUrl,
        apiClient: ApiClient(debugMode: widget.session.debugMode),
      );
      final health = await service.checkHealth();
      if (!mounted) {
        return;
      }
      setState(() {
        _health = health;
        _checking = false;
      });
      if (health.isHealthy) {
        await Future<void>.delayed(const Duration(milliseconds: 550));
        if (mounted) {
          widget.onReady(context);
        }
      }
    } catch (error) {
      if (!mounted) {
        return;
      }
      setState(() {
        _checking = false;
        _error = error.toString();
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    if (_error != null) {
      return Scaffold(
        body: SafeArea(
          child: ErrorView(
            title: 'Backend offline',
            message: _error!,
            onRetry: _checkHealth,
          ),
        ),
      );
    }

    return Scaffold(
      body: SafeArea(
        child: Center(
          child: FadeTransition(
            opacity: _controller,
            child: Padding(
              padding: const EdgeInsets.all(28),
              child: Column(
                mainAxisSize: MainAxisSize.min,
                children: [
                  Container(
                    width: 86,
                    height: 86,
                    decoration: BoxDecoration(
                      color: Theme.of(context).colorScheme.primary,
                      borderRadius: BorderRadius.circular(24),
                      boxShadow: const [
                        BoxShadow(
                          color: Color(0x332563EB),
                          blurRadius: 28,
                          offset: Offset(0, 14),
                        ),
                      ],
                    ),
                    child: const Icon(
                      Icons.hub_rounded,
                      color: Colors.white,
                      size: 44,
                    ),
                  ),
                  const SizedBox(height: 22),
                  Text(
                    'Enterprise Agentic RAG',
                    textAlign: TextAlign.center,
                    style: Theme.of(context).textTheme.headlineSmall?.copyWith(
                      fontWeight: FontWeight.w900,
                    ),
                  ),
                  const SizedBox(height: 10),
                  Text(
                    _checking
                        ? 'Checking backend health...'
                        : _health?.isHealthy == true
                        ? 'Backend online'
                        : 'Backend unavailable',
                    style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                      color: const Color(0xFF64748B),
                    ),
                  ),
                  const SizedBox(height: 24),
                  const CircularProgressIndicator(),
                ],
              ),
            ),
          ),
        ),
      ),
    );
  }
}
