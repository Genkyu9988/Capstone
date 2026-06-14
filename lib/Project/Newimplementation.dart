import 'package:flutter/material.dart';

void main() {
  runApp(const ElevatorNewDesignApp());
}

class ElevatorNewDesignApp extends StatelessWidget {
  const ElevatorNewDesignApp({Key? key}) : super(key: key);

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'Elevator Maintenance',
      theme: ThemeData(
        primaryColor: const Color(0xFFE32626), // Matching the vibrant red from the images
        scaffoldBackgroundColor: const Color(0xFFF5F7FA), // Light grey background
        appBarTheme: const AppBarTheme(
          backgroundColor: Color(0xFFE32626),
          elevation: 0,
          centerTitle: true,
          titleTextStyle: TextStyle(fontSize: 18, fontWeight: FontWeight.bold, color: Colors.white),
          iconTheme: IconThemeData(color: Colors.white),
        ),
        fontFamily: 'Roboto',
      ),
      home: const MainMenuScreen(),
      debugShowCheckedModeBanner: false,
    );
  }
}

// ==========================================
// SCREEN 1: MAIN MENU (Image 5)
// ==========================================
class MainMenuScreen extends StatelessWidget {
  const MainMenuScreen({Key? key}) : super(key: key);

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: const Color(0xFFEFF2F7),
      body: SafeArea(
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            // Top Left Profile Icon
            Padding(
              padding: const EdgeInsets.all(20.0),
              child: InkWell(
                onTap: () {
                  Navigator.push(
                    context,
                    MaterialPageRoute(builder: (context) => const ProfileScreen()),
                  );
                },
                child: Container(
                  padding: const EdgeInsets.all(12),
                  decoration: BoxDecoration(
                    color: Colors.white,
                    shape: BoxShape.circle,
                    boxShadow: [
                      BoxShadow(
                        color: Colors.black.withOpacity(0.05),
                        blurRadius: 10,
                        offset: const Offset(0, 4),
                      ),
                    ],
                  ),
                  child: const Icon(Icons.person, color: Color(0xFFE32626), size: 28),
                ),
              ),
            ),
            
            const Spacer(), // Pushes the menu to the center
            
            // Menu Items
            Center(
              child: Column(
                mainAxisAlignment: MainAxisAlignment.center,
                children: [
                  _buildMenuButton(
                    context,
                    icon: Icons.settings_applications_outlined,
                    title: 'Arıza Talep',
                    destination: const FaultRequestScreen(),
                  ),
                  const SizedBox(height: 30),
                  _buildMenuButton(
                    context,
                    icon: Icons.assignment_outlined,
                    title: 'İş Emri',
                    destination: const JobRequestScreen(),
                  ),
                  const SizedBox(height: 30),
                  _buildMenuButton(
                    context,
                    icon: Icons.insert_chart_outlined,
                    title: 'Dashboard',
                    destination: const DashboardScreen(),
                  ),
                ],
              ),
            ),
            
            const Spacer(flex: 2),
          ],
        ),
      ),
    );
  }

  // Custom widget to recreate the overlapping icon/text design
  Widget _buildMenuButton(BuildContext context, {required IconData icon, required String title, required Widget destination}) {
    return GestureDetector(
      onTap: () {
        Navigator.push(context, MaterialPageRoute(builder: (context) => destination));
      },
      child: SizedBox(
        width: 250,
        height: 80,
        child: Stack(
          alignment: Alignment.centerLeft,
          children: [
            // The grey text pill
            Positioned(
              left: 40,
              right: 0,
              child: Container(
                height: 50,
                decoration: BoxDecoration(
                  color: const Color(0xFFDEE5EE),
                  borderRadius: const BorderRadius.only(
                    topRight: Radius.circular(25),
                    bottomRight: Radius.circular(25),
                  ),
                ),
                alignment: Alignment.center,
                padding: const EdgeInsets.only(left: 30), // Padding to account for the overlapping box
                child: Text(
                  title,
                  style: const TextStyle(
                    fontSize: 16,
                    fontWeight: FontWeight.w600,
                    color: Color(0xFF4A5568),
                  ),
                ),
              ),
            ),
            // The white icon box
            Container(
              width: 80,
              height: 80,
              decoration: BoxDecoration(
                color: Colors.white,
                borderRadius: BorderRadius.circular(16),
                boxShadow: [
                  BoxShadow(
                    color: Colors.black.withOpacity(0.08),
                    blurRadius: 15,
                    offset: const Offset(0, 5),
                  ),
                ],
              ),
              child: Icon(icon, color: const Color(0xFFE32626), size: 40),
            ),
          ],
        ),
      ),
    );
  }
}

// ==========================================
// SCREEN 2: PROFILE (Image 1)
// ==========================================
class ProfileScreen extends StatelessWidget {
  const ProfileScreen({Key? key}) : super(key: key);

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('Profil'),
      ),
      body: SingleChildScrollView(
        padding: const EdgeInsets.all(20.0),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            // Top Red Profile Card
            Container(
              width: double.infinity,
              padding: const EdgeInsets.symmetric(vertical: 30),
              decoration: BoxDecoration(
                color: const Color(0xFFE32626),
                borderRadius: BorderRadius.circular(16),
              ),
              child: Column(
                children: [
                  Container(
                    padding: const EdgeInsets.all(16),
                    decoration: BoxDecoration(
                      color: Colors.white.withOpacity(0.2),
                      shape: BoxShape.circle,
                    ),
                    child: const Icon(Icons.person, color: Colors.white, size: 50),
                  ),
                  const SizedBox(height: 16),
                  const Text(
                    'Burak Uyanık',
                    style: TextStyle(color: Colors.white, fontSize: 22, fontWeight: FontWeight.bold),
                  ),
                  const SizedBox(height: 4),
                  const Text(
                    'Admin',
                    style: TextStyle(color: Colors.white70, fontSize: 14),
                  ),
                ],
              ),
            ),
            
            const SizedBox(height: 24),
            
            const Text('Kişisel Bilgiler', style: TextStyle(fontSize: 16, fontWeight: FontWeight.bold, color: Colors.grey)),
            const SizedBox(height: 12),
            
            // Info Card
            Container(
              decoration: BoxDecoration(
                color: Colors.white,
                borderRadius: BorderRadius.circular(12),
                border: Border.all(color: Colors.grey[300]!),
              ),
              child: Column(
                children: [
                  _buildProfileRow(Icons.person_outline, 'Ad Soyad', 'Burak Uyanık'),
                  const Divider(height: 1),
                  _buildProfileRow(Icons.mail_outline, 'Email', 'Belirtilmemiş'),
                  const Divider(height: 1),
                  _buildProfileRow(Icons.security_outlined, 'Rol', 'Admin'),
                ],
              ),
            ),
            
            const SizedBox(height: 24),
            const Text('Hesap İşlemleri', style: TextStyle(fontSize: 16, fontWeight: FontWeight.bold, color: Colors.grey)),
            const SizedBox(height: 12),
            
            // Action Cards
            _buildActionCard(Icons.key_outlined, 'Şifre Değiştir', Colors.teal),
            const SizedBox(height: 12),
            _buildActionCard(Icons.logout, 'Çıkış Yap', Colors.red),
          ],
        ),
      ),
    );
  }

  Widget _buildProfileRow(IconData icon, String label, String value) {
    return Padding(
      padding: const EdgeInsets.all(16.0),
      child: Row(
        children: [
          Icon(icon, color: Colors.red[300], size: 24),
          const SizedBox(width: 16),
          Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(label, style: const TextStyle(color: Colors.grey, fontSize: 12)),
              const SizedBox(height: 4),
              Text(value, style: const TextStyle(fontSize: 16, fontWeight: FontWeight.w500)),
            ],
          ),
        ],
      ),
    );
  }

  Widget _buildActionCard(IconData icon, String title, Color iconColor) {
    return Container(
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: Colors.grey[300]!),
      ),
      child: ListTile(
        leading: Icon(icon, color: iconColor),
        title: Text(title, style: TextStyle(color: iconColor, fontWeight: FontWeight.w500)),
        trailing: const Icon(Icons.chevron_right, color: Colors.grey),
        onTap: () {},
      ),
    );
  }
}

// ==========================================
// SCREEN 3: FAULT REQUEST FORM (Image 4)
// ==========================================
class FaultRequestScreen extends StatelessWidget {
  const FaultRequestScreen({Key? key}) : super(key: key);

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('Arıza Talep Formu'),
        actions: [
          IconButton(icon: const Icon(Icons.menu), onPressed: () {}),
        ],
      ),
      body: Padding(
        padding: const EdgeInsets.all(20.0),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Expanded(
              child: SingleChildScrollView(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    _buildLabel(Icons.build_circle_outlined, 'Ekipman'),
                    _buildDropdown('Ekipman Seçiniz'),
                    const SizedBox(height: 20),
                    
                    _buildLabel(Icons.settings_suggest_outlined, 'Makine Durumu'),
                    _buildDropdown('Makine Durumu Seçiniz'),
                    const SizedBox(height: 20),
                    
                    _buildLabel(Icons.calendar_today_outlined, 'Arıza Başlangıç Tarihi'),
                    Row(
                      children: [
                        Expanded(child: _buildTimeBox('26')),
                        const SizedBox(width: 8),
                        Expanded(flex: 2, child: _buildDropdown('Nisan')),
                        const SizedBox(width: 8),
                        Expanded(flex: 2, child: _buildTimeBox('2026')),
                      ],
                    ),
                    const SizedBox(height: 20),
                    
                    _buildLabel(Icons.access_time, 'Arıza Başlangıç Saati'),
                    Row(
                      children: [
                        _buildTimeBox('22'),
                        const Padding(
                          padding: EdgeInsets.symmetric(horizontal: 8.0),
                          child: Text(':', style: TextStyle(fontSize: 20, fontWeight: FontWeight.bold)),
                        ),
                        _buildTimeBox('17'),
                      ],
                    ),
                    const SizedBox(height: 20),
                    
                    Row(
                      children: [
                        SizedBox(
                          width: 24,
                          height: 24,
                          child: Checkbox(
                            value: false,
                            onChanged: (val) {},
                            side: const BorderSide(color: Colors.red),
                          ),
                        ),
                        const SizedBox(width: 8),
                        const Text('Arıza Tekrarı', style: TextStyle(fontSize: 16)),
                      ],
                    ),
                    const SizedBox(height: 20),
                    
                    // Text Area
                    Container(
                      height: 120,
                      decoration: BoxDecoration(
                        color: Colors.grey[200],
                        borderRadius: BorderRadius.circular(8),
                      ),
                      padding: const EdgeInsets.all(12),
                      child: const TextField(
                        maxLines: null,
                        decoration: InputDecoration(
                          border: InputBorder.none,
                          hintText: 'Arıza ile ilgili detaylı açıklama...',
                          hintStyle: TextStyle(color: Colors.grey),
                        ),
                      ),
                    ),
                  ],
                ),
              ),
            ),
            
            // Bottom Action Buttons
            Padding(
              padding: const EdgeInsets.only(top: 16.0, bottom: 8.0),
              child: Row(
                mainAxisAlignment: MainAxisAlignment.spaceEvenly,
                children: [
                  _buildCircularButton(Icons.settings, Colors.white, Colors.grey[400]!, hasBorder: true),
                  _buildCircularButton(Icons.close, Colors.red, Colors.white),
                  _buildCircularButton(Icons.check, Colors.green, Colors.white),
                  _buildCircularButton(Icons.image_outlined, Colors.blue, Colors.white),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }

  Widget _buildLabel(IconData icon, String text) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 8.0),
      child: Row(
        children: [
          Icon(icon, size: 18, color: Colors.grey[600]),
          const SizedBox(width: 8),
          Text(text, style: TextStyle(color: Colors.grey[700], fontSize: 14)),
        ],
      ),
    );
  }

  Widget _buildDropdown(String hint) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 4),
      decoration: BoxDecoration(
        color: Colors.grey[200],
        borderRadius: BorderRadius.circular(8),
      ),
      child: DropdownButtonHideUnderline(
        child: DropdownButton<String>(
          isExpanded: true,
          hint: Text(hint, style: const TextStyle(color: Colors.grey)),
          icon: const Icon(Icons.keyboard_arrow_down, color: Colors.grey),
          items: const [],
          onChanged: (val) {},
        ),
      ),
    );
  }

  Widget _buildTimeBox(String text) {
    return Container(
      padding: const EdgeInsets.symmetric(vertical: 12, horizontal: 16),
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(8),
        border: Border.all(color: Colors.grey[300]!),
      ),
      alignment: Alignment.center,
      child: Text(text, style: const TextStyle(fontSize: 16)),
    );
  }

  Widget _buildCircularButton(IconData icon, Color bgColor, Color iconColor, {bool hasBorder = false}) {
    return Container(
      width: 50,
      height: 50,
      decoration: BoxDecoration(
        color: bgColor,
        shape: BoxShape.circle,
        border: hasBorder ? Border.all(color: Colors.grey[300]!) : null,
        boxShadow: hasBorder ? [] : [
          BoxShadow(color: bgColor.withOpacity(0.4), blurRadius: 8, offset: const Offset(0, 4))
        ],
      ),
      child: IconButton(
        icon: Icon(icon, color: iconColor),
        onPressed: () {},
      ),
    );
  }
}

// ==========================================
// SCREEN 4: JOB REQUEST FORM (Image 3)
// ==========================================
class JobRequestScreen extends StatelessWidget {
  const JobRequestScreen({Key? key}) : super(key: key);

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('İş Talep Formu'),
        actions: [
          IconButton(icon: const Icon(Icons.menu), onPressed: () {}),
        ],
      ),
      body: Padding(
        padding: const EdgeInsets.all(20.0),
        child: Column(
          children: [
            Expanded(
              child: Container(
                decoration: BoxDecoration(
                  color: Colors.grey[100],
                  borderRadius: BorderRadius.circular(12),
                  border: Border.all(color: Colors.grey[300]!),
                ),
                child: Column(
                  children: [
                    // Location Dropdown
                    Container(
                      padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 4),
                      decoration: BoxDecoration(
                        border: Border(bottom: BorderSide(color: Colors.grey[300]!)),
                      ),
                      child: DropdownButtonHideUnderline(
                        child: DropdownButton<String>(
                          isExpanded: true,
                          hint: const Text('- Lokasyon Seçiniz -', style: TextStyle(color: Colors.grey)),
                          icon: const Icon(Icons.keyboard_arrow_down, color: Colors.grey),
                          items: const [],
                          onChanged: (val) {},
                        ),
                      ),
                    ),
                    // Text Area
                    Expanded(
                      child: Padding(
                        padding: const EdgeInsets.all(16.0),
                        child: const TextField(
                          maxLines: null,
                          decoration: InputDecoration(
                            border: InputBorder.none,
                            hintText: 'İş ile ilgili açıklama...',
                            hintStyle: TextStyle(color: Colors.grey),
                          ),
                        ),
                      ),
                    ),
                  ],
                ),
              ),
            ),
            
            // Bottom Action Buttons
            Padding(
              padding: const EdgeInsets.symmetric(vertical: 24.0),
              child: Row(
                mainAxisAlignment: MainAxisAlignment.center,
                children: [
                  _buildCircularButton(Icons.close, Colors.red, Colors.white),
                  const SizedBox(width: 24),
                  _buildCircularButton(Icons.check, Colors.green, Colors.white),
                  const SizedBox(width: 24),
                  _buildCircularButton(Icons.image_outlined, Colors.blue, Colors.white),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }

  Widget _buildCircularButton(IconData icon, Color bgColor, Color iconColor) {
    return Container(
      width: 50,
      height: 50,
      decoration: BoxDecoration(
        color: bgColor,
        shape: BoxShape.circle,
        boxShadow: [
          BoxShadow(color: bgColor.withOpacity(0.4), blurRadius: 8, offset: const Offset(0, 4))
        ],
      ),
      child: IconButton(
        icon: Icon(icon, color: iconColor),
        onPressed: () {},
      ),
    );
  }
}

// ==========================================
// SCREEN 5: DASHBOARD LOADING (Image 2)
// ==========================================
class DashboardScreen extends StatelessWidget {
  const DashboardScreen({Key? key}) : super(key: key);

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('Dashboard'),
        actions: [
          IconButton(icon: const Icon(Icons.menu), onPressed: () {}),
        ],
      ),
      body: Center(
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            const CircularProgressIndicator(
              valueColor: AlwaysStoppedAnimation<Color>(Color(0xFFE32626)),
              strokeWidth: 3,
            ),
            const SizedBox(height: 20),
            Text(
              'Üretim Hatları Yükleniyor...',
              style: TextStyle(color: Colors.grey[600], fontSize: 16),
            ),
          ],
        ),
      ),
    );
  }
}