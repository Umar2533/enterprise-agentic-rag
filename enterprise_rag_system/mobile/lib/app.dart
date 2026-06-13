import 'package:flutter/material.dart';

import 'core/storage/app_session.dart';
import 'core/theme/app_theme.dart';
import 'features/chat/presentation/screens/chat_screen.dart';
import 'features/home/presentation/home_screen.dart';
import 'features/knowledge_base/presentation/knowledge_base_screen.dart';
import 'features/settings/presentation/settings_screen.dart';
import 'features/splash/presentation/splash_screen.dart';
import 'features/upload/presentation/upload_screen.dart';

class EnterpriseRagApp extends StatefulWidget {
  const EnterpriseRagApp({super.key});

  @override
  State<EnterpriseRagApp> createState() => _EnterpriseRagAppState();
}

class _EnterpriseRagAppState extends State<EnterpriseRagApp> {
  final AppSession _session = AppSession();
  bool _loaded = false;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    await _session.load();
    if (mounted) {
      setState(() => _loaded = true);
    }
  }

  @override
  Widget build(BuildContext context) {
    return ListenableBuilder(
      listenable: _session,
      builder: (context, _) {
        return MaterialApp(
          title: 'Enterprise Agentic RAG',
          debugShowCheckedModeBanner: false,
          theme: AppTheme.lightTheme,
          darkTheme: AppTheme.darkTheme,
          themeMode: _session.themeMode,
          home: _loaded
              ? SplashScreen(
                  session: _session,
                  onReady: (splashContext) {
                    Navigator.of(splashContext).pushReplacement(
                      MaterialPageRoute(
                        builder: (_) => AppShell(session: _session),
                      ),
                    );
                  },
                )
              : const Scaffold(
                  body: Center(child: CircularProgressIndicator()),
                ),
        );
      },
    );
  }
}

class AppShell extends StatefulWidget {
  const AppShell({required this.session, super.key});

  final AppSession session;

  @override
  State<AppShell> createState() => _AppShellState();
}

class _AppShellState extends State<AppShell> {
  static const int _homeTabIndex = 0;
  static const int _chatTabIndex = 3;
  static const int _tabCount = 5;

  int _index = _homeTabIndex;
  int _previousNonChatIndex = _homeTabIndex;

  @override
  Widget build(BuildContext context) {
    final pages = [
      HomeScreen(session: widget.session, onNavigate: _setIndex),
      KnowledgeBaseScreen(session: widget.session),
      UploadScreen(session: widget.session),
      ChatScreen(session: widget.session, onExitChat: _exitChat),
      SettingsScreen(session: widget.session),
    ];

    return Scaffold(
      body: pages[_index],
      bottomNavigationBar: _index == _chatTabIndex
          ? null
          : NavigationBar(
              height: 64,
              elevation: 1,
              indicatorShape: RoundedRectangleBorder(
                borderRadius: BorderRadius.circular(18),
              ),
              selectedIndex: _index,
              onDestinationSelected: _setIndex,
              destinations: const [
                NavigationDestination(
                  icon: Icon(Icons.dashboard_outlined),
                  selectedIcon: Icon(Icons.dashboard_rounded),
                  label: 'Home',
                ),
                NavigationDestination(
                  icon: Icon(Icons.folder_outlined),
                  selectedIcon: Icon(Icons.folder_rounded),
                  label: 'Knowledge',
                ),
                NavigationDestination(
                  icon: Icon(Icons.upload_file_outlined),
                  selectedIcon: Icon(Icons.upload_file_rounded),
                  label: 'Upload',
                ),
                NavigationDestination(
                  icon: Icon(Icons.chat_bubble_outline_rounded),
                  selectedIcon: Icon(Icons.chat_bubble_rounded),
                  label: 'Chat',
                ),
                NavigationDestination(
                  icon: Icon(Icons.settings_outlined),
                  selectedIcon: Icon(Icons.settings_rounded),
                  label: 'Settings',
                ),
              ],
            ),
    );
  }

  void _setIndex(int index) {
    setState(() {
      if (index != _chatTabIndex) {
        _previousNonChatIndex = index;
      }
      _index = index;
    });
  }

  void _exitChat() {
    final previousIndexIsValid =
        _previousNonChatIndex >= 0 &&
        _previousNonChatIndex < _tabCount &&
        _previousNonChatIndex != _chatTabIndex;
    final destination = !previousIndexIsValid
        ? _homeTabIndex
        : _previousNonChatIndex;
    _setIndex(destination);
  }
}
