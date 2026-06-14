import 'dart:convert';
import 'dart:math';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:http/http.dart' as http;

// Backend API — the SAME source the web admin dashboard uses, so the phone and
// the dashboard always show identical data (the database is the source of truth).
//   - Android emulator: reach the host PC via 10.0.2.2 (NOT localhost).
//   - Physical phone:   use your PC's LAN IP, e.g. http://192.168.1.20:8080
//   - Flutter web:      use http://localhost:8080
const String kApiBase = 'http://10.0.2.2:8080';
const String kVehiclesUrl = '$kApiBase/api/vehicles';

// =============================================================================
// Anıl Galeri — Luxury Car Sales Gallery
//
// Single-file, SDK-only (no extra pub packages) so it runs as-is.
// Features needing a package are implemented with a working fallback and
// marked `// UPGRADE:` with the exact one-line swap.
// =============================================================================

void main() {
  runApp(const AnilGaleriApp());
}

class AnilGaleriApp extends StatelessWidget {
  const AnilGaleriApp({super.key});

  @override
  Widget build(BuildContext context) {
    return ListenableBuilder(
      listenable: AppSettings.instance,
      builder: (context, _) {
        return MaterialApp(
          debugShowCheckedModeBanner: false,
          title: 'Anıl Galeri',
          theme: ThemeData(
            useMaterial3: true,
            brightness: Brightness.dark,
            scaffoldBackgroundColor: AppColors.background,
            colorScheme: const ColorScheme.dark(
              primary: AppColors.gold,
              secondary: AppColors.card,
              surface: AppColors.card,
            ),
          ),
          home: const LoginScreen(),
        );
      },
    );
  }
}

class AppColors {
  static const Color background = Color(0xFF111113);
  static const Color card = Color(0xFF1E1E24);
  static const Color cardLight = Color(0xFF292932);
  static const Color gold = Color(0xFFE8C423);
  static const Color muted = Color(0xFF9E9EAA);
  static const Color green = Color(0xFF00D26A);
  static const Color red = Color(0xFFFF3B45);
}

class AppHaptics {
  static Future<void> light() => HapticFeedback.selectionClick();
  static Future<void> medium() => HapticFeedback.mediumImpact();
}

const String kDealerPhone = '+90 555 000 00 00';
const String kDealerWhatsApp = '+90 555 000 00 00';

// =============================================================================
// SETTINGS · LOCALIZATION · CURRENCY
// =============================================================================

enum AppLanguage { en, tr }
enum AppCurrency { usd, tl }

/// Static mock rate. UPGRADE: fetch a live FX rate from an API.
const double kUsdToTl = 38.5;

/// App-wide settings. NOTE: in-memory only.
/// UPGRADE: persist with shared_preferences in the setters.
class AppSettings extends ChangeNotifier {
  static final AppSettings instance = AppSettings._();
  AppSettings._();

  AppLanguage language = AppLanguage.en;
  AppCurrency currency = AppCurrency.usd;
  String? preferredLocationId; // null = all locations

  void setLanguage(AppLanguage value) {
    language = value;
    notifyListeners();
  }

  void setCurrency(AppCurrency value) {
    currency = value;
    notifyListeners();
  }

  void setPreferredLocation(String? id) {
    preferredLocationId = id;
    notifyListeners();
  }
}

/// Lightweight i18n. English is the source; Turkish overrides it.
String tr(String en) {
  if (AppSettings.instance.language == AppLanguage.en) return en;
  return _trMap[en] ?? en;
}

const Map<String, String> _trMap = {
  'Luxury dealership system': 'Lüks galeri sistemi',
  'Email': 'E-posta',
  'Password': 'Şifre',
  'Login': 'Giriş Yap',
  'Please enter email and password.': 'Lütfen e-posta ve şifre girin.',
  'Use admin@anilgaleri.com for admin mode.':
      'Yönetici modu için admin@anilgaleri.com kullanın.',
  'Browse': 'Keşfet',
  'Favorites': 'Favoriler',
  'Settings': 'Ayarlar',
  'Premium Cars': 'Premium Araçlar',
  'Admin Panel': 'Yönetici Paneli',
  'Search brand or model...': 'Marka veya model ara...',
  'Featured Deals': 'Öne Çıkan Fırsatlar',
  'No hot deals found.': 'Fırsat bulunamadı.',
  'Available Inventory': 'Mevcut Stok',
  'Cars': 'Araç',
  'Filters': 'Filtreler',
  'Apply Filters': 'Filtreleri Uygula',
  'SUV': 'SUV',
  'Sedan': 'Sedan',
  'Electric': 'Elektrik',
  'No vehicles found. Try changing filters.':
      'Araç bulunamadı. Filtreleri değiştirin.',
  'Load more': 'Daha fazla yükle',
  'Sort': 'Sırala',
  'Price': 'Fiyat',
  'Price: Low to High': 'Fiyat: Artan',
  'Price: High to Low': 'Fiyat: Azalan',
  'Newest year': 'En yeni model',
  'Lowest mileage': 'En düşük km',
  'Hot Deal': 'Fırsat',
  'Great Price': 'Uygun Fiyat',
  'HOT DEAL': 'FIRSAT',
  'Technical Specs': 'Teknik Özellikler',
  'Description': 'Açıklama',
  'Contact Dealer': 'Galeriyi Ara',
  'Top Speed': 'Maks. Hız',
  'Power': 'Güç',
  'Battery': 'Batarya',
  'Engine': 'Motor',
  'Range': 'Menzil',
  'Color': 'Renk',
  'Financing': 'Finansman',
  'Book a Test Drive': 'Test Sürüşü Ayarla',
  'Offer Your Trade-In': 'Takas Teklif Et',
  'Similar Vehicles': 'Benzer Araçlar',
  'VEHICLE CONDITION (EXPERTISE)': 'ARAÇ DURUMU (EKSPERTİZ)',
  'Details Available': 'Detaylar Mevcut',
  'No Damage': 'Hasarsız',
  'Original': 'Orijinal',
  'Painted': 'Boyalı',
  'Replaced': 'Değişen',
  'Down Payment': 'Peşinat',
  'Term': 'Vade',
  'Bank': 'Banka',
  'Monthly Payment': 'Aylık Taksit',
  'Total Payable': 'Toplam Ödeme',
  'Total Interest': 'Toplam Faiz',
  'months': 'ay',
  'This vehicle is not eligible for financing.':
      'Bu araç finansmana uygun değil.',
  'How would you like to reach us?': 'Bize nasıl ulaşmak istersiniz?',
  'Call': 'Ara',
  'WhatsApp': 'WhatsApp',
  'Send a message': 'Mesaj gönder',
  'Inspection Report': 'Ekspertiz Raporu',
  'Original Body': 'Orijinal Gövde',
  'Certified by Anıl Galeri Experts': 'Anıl Galeri Eksperleri Onaylı',
  'Tramer / Damage History': 'Tramer / Hasar Kaydı',
  'No official insurance records': 'Resmi sigorta kaydı yok',
  'record found': 'kayıt bulundu',
  'This vehicle has no recorded damage history.':
      'Bu araçta kayıtlı hasar geçmişi yok.',
  'Cost': 'Maliyet',
  'Bank Offers': 'Banka Teklifleri',
  'Interest': 'Faiz',
  'Max tenure': 'Maks. vade',
  'Compare': 'Karşılaştır',
  'Compare Vehicles': 'Araç Karşılaştır',
  'Select cars to compare': 'Karşılaştırmak için araç seçin',
  'Attribute': 'Özellik',
  'Year': 'Yıl',
  'Mileage': 'Kilometre',
  'Fuel': 'Yakıt',
  'Transmission': 'Vites',
  'Body': 'Kasa',
  '0-100 km/h': '0-100 km/s',
  'Drivetrain': 'Çekiş',
  'Original %': 'Orijinal %',
  'Clear': 'Temizle',
  'No favorites yet': 'Henüz favori yok',
  'Tap the heart on any car to save it here.':
      'Bir aracı kaydetmek için kalbe dokunun.',
  'Language': 'Dil',
  'Currency': 'Para Birimi',
  'English': 'İngilizce',
  'Turkish': 'Türkçe',
  'Logout': 'Çıkış Yap',
  'Trade-In Request': 'Takas Talebi',
  'Your car brand': 'Aracınızın markası',
  'Your car model': 'Aracınızın modeli',
  'Your name': 'Adınız',
  'Phone': 'Telefon',
  'Notes (optional)': 'Notlar (isteğe bağlı)',
  'Condition': 'Durum',
  'Submit Request': 'Talebi Gönder',
  'Trade-in request sent. We will call you soon.':
      'Takas talebi gönderildi. Sizi en kısa sürede arayacağız.',
  'Excellent': 'Çok İyi',
  'Good': 'İyi',
  'Average': 'Orta',
  'Poor': 'Kötü',
  'Test Drive Booking': 'Test Sürüşü Randevusu',
  'Pick a date': 'Tarih seçin',
  'Pick a time': 'Saat seçin',
  'Confirm Booking': 'Randevuyu Onayla',
  'Test drive booked. See you at the showroom!':
      'Test sürüşü ayarlandı. Showroom\'da görüşürüz!',
  'Manage Vehicles': 'Araç Yönetimi',
  'Add Vehicle': 'Araç Ekle',
  'Edit Vehicle': 'Araç Düzenle',
  'Delete vehicle?': 'Aracı sil?',
  'This action cannot be undone.': 'Bu işlem geri alınamaz.',
  'Cancel': 'İptal',
  'Delete': 'Sil',
  'Save': 'Kaydet',
  'Brand': 'Marka',
  'Model': 'Model',
  'Trim / Package': 'Donanım / Paket',
  'Price (USD)': 'Fiyat (USD)',
  'Image URL': 'Görsel URL',
  'Hot deal': 'Fırsat',
  'Loan eligible': 'Krediye uygun',
  'Accepts trade-in': 'Takas kabul',
  'Required': 'Zorunlu',
  'Enter a valid number': 'Geçerli bir sayı girin',
  'Vehicle loading error': 'Araç yükleme hatası',
  'Retry': 'Tekrar Dene',
  'From': '',
  // Locations
  'Locations': 'Lokasyonlar',
  'All Locations': 'Tüm Lokasyonlar',
  'Location': 'Lokasyon',
  'Preferred Location': 'Tercih Edilen Lokasyon',
  'Available now at': 'Şu an mevcut:',
  'Available now': 'Stokta',
  'Not in stock': 'Stokta yok',
  'Pre-order': 'Ön Sipariş',
  'You save': 'Tasarruf',
  'available': 'adet',
  'Currently unavailable': 'Şu anda mevcut değil',
  'Warehouse': 'Depo',
  'for pre-order': 'ön sipariş',
  'Pre-order stock': 'Ön sipariş stoğu',
  'No cars available to pre-order right now.': 'Şu anda ön sipariş verilecek araç yok.',
  'Galleries': 'Galeriler',
  'In our warehouse — pre-order and pick your gallery.': 'Depomuzda — ön sipariş verip galeri seçin.',
  'Browse & filter this gallery': 'Bu galeriyi görüntüle ve filtrele',
  'Gallery': 'Galeri',
  'Front bumper': 'Ön tampon',
  'Rear bumper': 'Arka tampon',
  'Left front door': 'Sol ön kapı',
  'Right front door': 'Sağ ön kapı',
  'Left rear door': 'Sol arka kapı',
  'Right rear door': 'Sağ arka kapı',
  'Hood': 'Kaput',
  'Roof': 'Tavan',
  'Where would you like to pick it up?': 'Aracı nereden teslim almak istersiniz?',
  'Order for future delivery': 'İleri tarihli sipariş',
  'Reserve this car': 'Bu aracı rezerve et',
  'Pre-order this car': 'Bu aracı ön sipariş ver',
  'Go to Locations to reserve or pre-order this car.': 'Rezervasyon veya ön sipariş için Lokasyonlar sekmesine gidin.',
  'Confirm reservation': 'Rezervasyonu onayla',
  'Confirm pre-order': 'Ön siparişi onayla',
  'In stock - reserve now': 'Stokta - hemen rezerve et',
  'Not in stock - order for future delivery':
      'Stokta yok - ileri tarih için sipariş ver',
  'Reservation sent. The dealership will contact you.':
      'Rezervasyon gönderildi. Galeri sizinle iletişime geçecek.',
  'Pre-order sent. The dealership will contact you.':
      'Ön sipariş gönderildi. Galeri sizinle iletişime geçecek.',
  'Could not send. Check your connection and try again.':
      'Gönderilemedi. Bağlantınızı kontrol edip tekrar deneyin.',
  'Email (optional)': 'E-posta (isteğe bağlı)',
  'Where is this car?': 'Bu araç nerede?',
  'View on map': 'Haritada gör',
  'cars here': 'araç burada',
  'No cars at this location.': 'Bu lokasyonda araç yok.',
  'This car is not currently in stock. You can order it for a future date.':
      'Bu araç şu an stokta değil. İleri bir tarih için sipariş verebilirsiniz.',
  'Hide Damaged / Painted Vehicles': 'Hasarlı / Boyalı Araçları Gizle',
  'Performance': 'Performans',
  'Surprise me': 'Beni şaşırt',
  'Torque': 'Tork',
  'Electric Range': 'Elektrik Menzili',
};

String formatMoney(double usdAmount) {
  if (AppSettings.instance.currency == AppCurrency.tl) {
    return '₺${_formatNumber((usdAmount * kUsdToTl).round())}';
  }
  return '\$${_formatNumber(usdAmount.round())}';
}

// =============================================================================
// ROUTING
// =============================================================================

class LuxuryPageRoute<T> extends PageRouteBuilder<T> {
  final Widget child;

  LuxuryPageRoute({required this.child})
      : super(
          transitionDuration: const Duration(milliseconds: 520),
          reverseTransitionDuration: const Duration(milliseconds: 380),
          pageBuilder: (context, animation, secondaryAnimation) => child,
          transitionsBuilder: (context, animation, secondaryAnimation, child) {
            final curved = CurvedAnimation(
              parent: animation,
              curve: Curves.easeOutCubic,
              reverseCurve: Curves.easeInCubic,
            );
            return FadeTransition(
              opacity: curved,
              child: ScaleTransition(
                scale: Tween<double>(begin: 0.985, end: 1).animate(curved),
                child: child,
              ),
            );
          },
        );
}

// =============================================================================
// ENUMS
// =============================================================================

enum FuelType { petrol, diesel, electric, hybrid }
enum Transmission { automatic, manual, semiAutomatic }
enum BodyType { suv, sedan, coupe, hatchback, pickup, cabrio, wagon }
enum PartStatus { original, painted, replaced }
enum SortOption { priceAsc, priceDesc, yearDesc, mileageAsc }

extension FuelTypeText on FuelType {
  String get label {
    switch (this) {
      case FuelType.petrol:
        return 'Petrol';
      case FuelType.diesel:
        return 'Diesel';
      case FuelType.electric:
        return 'Electric';
      case FuelType.hybrid:
        return 'Hybrid';
    }
  }

  String get localizedLabel => tr(label);
}

extension TransmissionText on Transmission {
  String get label {
    switch (this) {
      case Transmission.automatic:
        return 'Automatic';
      case Transmission.manual:
        return 'Manual';
      case Transmission.semiAutomatic:
        return 'Semi Automatic';
    }
  }

  String get localizedLabel => tr(label);
}

extension BodyTypeText on BodyType {
  String get label {
    switch (this) {
      case BodyType.suv:
        return 'SUV';
      case BodyType.sedan:
        return 'Sedan';
      case BodyType.coupe:
        return 'Coupe';
      case BodyType.hatchback:
        return 'Hatchback';
      case BodyType.pickup:
        return 'Pickup';
      case BodyType.cabrio:
        return 'Cabrio';
      case BodyType.wagon:
        return 'Wagon';
    }
  }

  String get localizedLabel => tr(label);
}

extension SortOptionText on SortOption {
  String get label {
    switch (this) {
      case SortOption.priceAsc:
        return 'Price: Low to High';
      case SortOption.priceDesc:
        return 'Price: High to Low';
      case SortOption.yearDesc:
        return 'Newest year';
      case SortOption.mileageAsc:
        return 'Lowest mileage';
    }
  }
}

// =============================================================================
// MODELS
// =============================================================================

class AppUser {
  final String id;
  final String fullName;
  final String email;
  final String role;

  const AppUser({
    required this.id,
    required this.fullName,
    required this.email,
    required this.role,
  });

  bool get isAdmin => role == 'ADMIN';
}

class VehicleImage {
  final String id;
  final String vehicleId;
  final String imageUrl;
  final bool isCover;
  final int sortOrder;

  const VehicleImage({
    required this.id,
    required this.vehicleId,
    required this.imageUrl,
    required this.isCover,
    required this.sortOrder,
  });
}

class VehicleSpecs {
  final String vehicleId;
  final int powerHp;
  final int topSpeed;
  final double zeroToHundred;
  final int engineCc;
  final int torque;
  final double batteryKwh;
  final int rangeKm;
  final String color;
  final String drivetrain;

  const VehicleSpecs({
    required this.vehicleId,
    required this.powerHp,
    required this.topSpeed,
    required this.zeroToHundred,
    required this.engineCc,
    required this.torque,
    required this.batteryKwh,
    required this.rangeKm,
    required this.color,
    required this.drivetrain,
  });
}

class VehicleInspection {
  final String vehicleId;
  final PartStatus hood;
  final PartStatus roof;
  final PartStatus frontBumper;
  final PartStatus rearBumper;
  final PartStatus leftFrontDoor;
  final PartStatus rightFrontDoor;
  final PartStatus leftRearDoor;
  final PartStatus rightRearDoor;
  final double tramerAmount;

  const VehicleInspection({
    required this.vehicleId,
    required this.hood,
    required this.roof,
    required this.frontBumper,
    required this.rearBumper,
    required this.leftFrontDoor,
    required this.rightFrontDoor,
    required this.leftRearDoor,
    required this.rightRearDoor,
    required this.tramerAmount,
  });

  List<PartStatus> get allParts => [
        hood,
        roof,
        frontBumper,
        rearBumper,
        leftFrontDoor,
        rightFrontDoor,
        leftRearDoor,
        rightRearDoor,
      ];

  bool get hasDamage =>
      tramerAmount > 0 || allParts.any((part) => part != PartStatus.original);
}

class VehicleDamageHistory {
  final String id;
  final String vehicleId;
  final DateTime damageDate;
  final String title;
  final String description;
  final double cost;
  final String damageType;

  const VehicleDamageHistory({
    required this.id,
    required this.vehicleId,
    required this.damageDate,
    required this.title,
    required this.description,
    required this.cost,
    required this.damageType,
  });
}

/// A physical dealership / gallery location.
class GalleryLocation {
  final String id;
  final String name;
  final String city;
  final String address;
  final double latitude;
  final double longitude;

  const GalleryLocation({
    required this.id,
    required this.name,
    required this.city,
    required this.address,
    required this.latitude,
    required this.longitude,
  });

  /// District shown to customers (e.g. "Maslak"), derived from the name.
  String get district => name.replaceFirst('Anıl Galeri ', '').trim();
}

class Vehicle {
  final String id;
  final String brand;
  final String model;
  final String trimPackage;
  final double price; // USD base
  final String currency;
  final int year;
  final int mileage;
  final FuelType fuelType;
  final Transmission transmission;
  final BodyType bodyType;
  final bool isHotDeal;
  final bool isLoanEligible;
  final bool acceptsTradeIn;
  final String description;
  final VehicleSpecs specs;
  final VehicleInspection inspection;
  final List<VehicleImage> images;
  final List<VehicleDamageHistory> damageHistory;
  final String locationId; // which gallery this car physically sits at
  final bool inStock; // true = available now, false = orderable for the future

  const Vehicle({
    required this.id,
    required this.brand,
    required this.model,
    required this.trimPackage,
    required this.price,
    required this.currency,
    required this.year,
    required this.mileage,
    required this.fuelType,
    required this.transmission,
    required this.bodyType,
    required this.isHotDeal,
    required this.isLoanEligible,
    required this.acceptsTradeIn,
    required this.description,
    required this.specs,
    required this.inspection,
    required this.images,
    required this.damageHistory,
    this.locationId = '',
    this.inStock = true,
  });

  GalleryLocation? get location =>
      VehicleService.instance.locationById(locationId);

  String get fullName =>
      trimPackage.trim().isEmpty ? '$brand $model' : '$brand $model $trimPackage';

  String get coverImage {
    if (images.isEmpty) return '';
    return images
        .firstWhere((image) => image.isCover, orElse: () => images.first)
        .imageUrl;
  }

  List<String> get galleryUrls {
    final sorted = [...images]..sort((a, b) => a.sortOrder.compareTo(b.sortOrder));
    return sorted.map((e) => e.imageUrl).toList();
  }

  String get formattedPrice => formatMoney(price);

  // Hot-deal cars are automatically 10% off the listed price.
  double get salePrice => isHotDeal ? price * 0.9 : price;
  String get formattedSalePrice => formatMoney(salePrice);
  String get formattedSavings => formatMoney(price - salePrice);
  String get formattedMileage => '${_formatNumber(mileage)} km';

  bool matchesSearch(String query) {
    if (query.trim().isEmpty) return true;
    final q = query.toLowerCase();
    return fullName.toLowerCase().contains(q) ||
        brand.toLowerCase().contains(q) ||
        model.toLowerCase().contains(q);
  }
}

String _formatNumber(int number) {
  return number.toString().replaceAllMapped(
        RegExp(r'\B(?=(\d{3})+(?!\d))'),
        (match) => ',',
      );
}

class VehicleFilter {
  String? brand;
  BodyType? bodyType;
  FuelType? fuelType;
  Transmission? transmission;
  String? locationId;
  double minPrice;
  double maxPrice;
  int minYear;
  int maxYear;
  bool hideDamaged;
  bool showPerformanceOnly;

  VehicleFilter({
    this.brand,
    this.bodyType,
    this.fuelType,
    this.transmission,
    this.locationId,
    this.minPrice = 10000,
    this.maxPrice = 300000,
    this.minYear = 2015,
    this.maxYear = 2026,
    this.hideDamaged = false,
    this.showPerformanceOnly = false,
  });

  bool matches(Vehicle vehicle) {
    if (brand != null && vehicle.brand != brand) return false;
    if (bodyType != null && vehicle.bodyType != bodyType) return false;
    if (fuelType != null && vehicle.fuelType != fuelType) return false;
    if (transmission != null && vehicle.transmission != transmission) return false;
    if (locationId != null && vehicle.locationId != locationId) return false;
    if (hideDamaged && vehicle.inspection.hasDamage) return false;
    if (showPerformanceOnly && vehicle.specs.zeroToHundred > 4.0) return false;
    if (vehicle.price < minPrice || vehicle.price > maxPrice) return false;
    if (vehicle.year < minYear || vehicle.year > maxYear) return false;
    return true;
  }

  VehicleFilter copy() => VehicleFilter(
        brand: brand,
        bodyType: bodyType,
        fuelType: fuelType,
        transmission: transmission,
        locationId: locationId,
        minPrice: minPrice,
        maxPrice: maxPrice,
        minYear: minYear,
        maxYear: maxYear,
        hideDamaged: hideDamaged,
        showPerformanceOnly: showPerformanceOnly,
      );
}

// =============================================================================
// SERVICES
// =============================================================================

class DatabaseConnection {
  static final DatabaseConnection instance = DatabaseConnection._internal();
  DatabaseConnection._internal();

  Future<String> getConnection() async {
    await Future.delayed(const Duration(milliseconds: 100));
    return 'Mock database connection established';
  }
}

class AuthService {
  Future<AppUser?> login(String email, String password) async {
    await DatabaseConnection.instance.getConnection();
    await Future.delayed(const Duration(milliseconds: 350));

    if (email.trim().isEmpty || password.trim().isEmpty) return null;

    final role = email.toLowerCase().contains('admin') ? 'ADMIN' : 'USER';
    return AppUser(
      id: 'user-001',
      fullName: role == 'ADMIN' ? 'Admin User' : 'Anıl Galeri Customer',
      email: email.trim(),
      role: role,
    );
  }
}

// Safe enum lookup by name with a fallback (tolerant of bad data).
T _enumByName<T extends Enum>(List<T> values, Object? name, T fallback) {
  final s = name?.toString();
  for (final v in values) {
    if (v.name == s) return v;
  }
  return fallback;
}

double _asDouble(Object? v) =>
    v is num ? v.toDouble() : double.tryParse(v?.toString() ?? '') ?? 0;
int _asInt(Object? v) =>
    v is num ? v.toInt() : int.tryParse(v?.toString() ?? '') ?? 0;

class VehicleFactory {
  Vehicle createVehicle(Map<String, dynamic> rs) {
    final id = rs['id'] as String;
    final specsJson = (rs['specs'] as Map?)?.cast<String, dynamic>() ?? {};
    final inspJson = (rs['inspection'] as Map?)?.cast<String, dynamic>() ?? {};

    // images may be a list of URL strings (JSON) or VehicleImage objects (code).
    final rawImages = (rs['images'] as List?) ?? const [];
    final images = <VehicleImage>[];
    for (var i = 0; i < rawImages.length; i++) {
      final item = rawImages[i];
      if (item is VehicleImage) {
        images.add(item);
      } else {
        images.add(VehicleImage(
          id: '$id-img$i',
          vehicleId: id,
          imageUrl: item.toString(),
          isCover: i == 0,
          sortOrder: i + 1,
        ));
      }
    }

    PartStatus part(String key) =>
        _enumByName(PartStatus.values, inspJson[key], PartStatus.original);

    return Vehicle(
      id: id,
      brand: rs['brand'] as String,
      model: rs['model'] as String,
      trimPackage: (rs['trimPackage'] as String?) ?? '',
      price: _asDouble(rs['price']),
      currency: (rs['currency'] as String?) ?? r'$',
      year: _asInt(rs['year']),
      mileage: _asInt(rs['mileage']),
      fuelType: _enumByName(FuelType.values, rs['fuelType'], FuelType.petrol),
      transmission: _enumByName(
          Transmission.values, rs['transmission'], Transmission.automatic),
      bodyType: _enumByName(BodyType.values, rs['bodyType'], BodyType.sedan),
      isHotDeal: (rs['isHotDeal'] as bool?) ?? false,
      isLoanEligible: (rs['isLoanEligible'] as bool?) ?? true,
      acceptsTradeIn: (rs['acceptsTradeIn'] as bool?) ?? false,
      description: (rs['description'] as String?) ?? '',
      specs: VehicleSpecs(
        vehicleId: id,
        powerHp: _asInt(specsJson['powerHp']),
        topSpeed: _asInt(specsJson['topSpeed']),
        zeroToHundred: _asDouble(specsJson['zeroToHundred']),
        engineCc: _asInt(specsJson['engineCc']),
        torque: _asInt(specsJson['torque']),
        batteryKwh: _asDouble(specsJson['batteryKwh']),
        rangeKm: _asInt(specsJson['rangeKm']),
        color: (specsJson['color'] as String?) ?? '',
        drivetrain: (specsJson['drivetrain'] as String?) ?? 'AWD',
      ),
      inspection: VehicleInspection(
        vehicleId: id,
        hood: part('hood'),
        roof: part('roof'),
        frontBumper: part('frontBumper'),
        rearBumper: part('rearBumper'),
        leftFrontDoor: part('leftFrontDoor'),
        rightFrontDoor: part('rightFrontDoor'),
        leftRearDoor: part('leftRearDoor'),
        rightRearDoor: part('rightRearDoor'),
        tramerAmount: _asDouble(inspJson['tramerAmount']),
      ),
      images: images,
      damageHistory: const [],
      locationId: (rs['locationId'] as String?) ?? '',
      inStock: (rs['inStock'] as bool?) ?? true,
    );
  }
}

/// Centralized, app-wide store (the "state management" improvement).
/// Holds inventory, favorites, compare selection and leads, and notifies UI.
/// NOTE: favorites are in-memory. UPGRADE: persist with shared_preferences.
class VehicleService extends ChangeNotifier {
  static final VehicleService instance = VehicleService._internal();
  VehicleService._internal();

  final VehicleFactory _factory = VehicleFactory();
  final List<Vehicle> _vehicles = [];

  bool _loaded = false;
  bool _loading = false;
  String? _error;

  bool get isLoading => _loading;
  String? get error => _error;
  List<Vehicle> get vehicles => List.unmodifiable(_vehicles);

  // ---- Locations ----
  List<GalleryLocation> get locations => _galleryLocations;

  GalleryLocation? locationById(String id) {
    for (final loc in _galleryLocations) {
      if (loc.id == id) return loc;
    }
    return null;
  }

  List<Vehicle> vehiclesAtLocation(String locationId) =>
      _vehicles.where((v) => v.locationId == locationId).toList();

  Future<void> ensureLoaded({bool force = false}) async {
    if (_loaded && !force) return;
    _loading = true;
    _error = null;
    notifyListeners();
    try {
      // Single source of truth: the Java backend / database (same as the web admin).
      final res = await http
          .get(Uri.parse(kVehiclesUrl))
          .timeout(const Duration(seconds: 12));
      if (res.statusCode != 200) {
        throw 'Server returned ${res.statusCode}';
      }
      final List<dynamic> rows = jsonDecode(res.body) as List<dynamic>;
      _vehicles
        ..clear()
        ..addAll(rows.map(
            (row) => _factory.createVehicle((row as Map).cast<String, dynamic>())));
      _loaded = true;
    } catch (e) {
      _error =
          'Could not reach the backend at $kApiBase.\nMake sure it is running, then retry.';
    } finally {
      _loading = false;
      notifyListeners();
    }
  }

  void addVehicle(Vehicle vehicle) {
    _vehicles.add(vehicle);
    notifyListeners();
  }

  void updateVehicle(Vehicle vehicle) {
    final i = _vehicles.indexWhere((v) => v.id == vehicle.id);
    if (i >= 0) {
      _vehicles[i] = vehicle;
      notifyListeners();
    }
  }

  void deleteVehicle(String id) {
    _vehicles.removeWhere((v) => v.id == id);
    notifyListeners();
  }

  // ---- Demand side: send requests to the backend ----
  Future<void> createOrder({
    required String vehicleId,
    required String customerName,
    required String phone,
    required String email,
    required String type, // RESERVE or PREORDER
    required String note,
    String targetLocationId = '',
  }) async {
    final res = await http
        .post(Uri.parse('$kApiBase/api/orders'),
            headers: {'Content-Type': 'application/json'},
            body: jsonEncode({
              'vehicleId': vehicleId,
              'customerName': customerName,
              'phone': phone,
              'email': email,
              'type': type,
              'note': note,
              'targetLocationId': targetLocationId,
            }))
        .timeout(const Duration(seconds: 12));
    if (res.statusCode < 200 || res.statusCode >= 300) {
      throw 'Server returned ${res.statusCode}';
    }
  }

  String nextVehicleId() => 'v${DateTime.now().millisecondsSinceEpoch}';
}

// =============================================================================
// MOCK DATA
// =============================================================================

// Vehicle data lives in assets/cars.json (loaded at runtime). Gallery
// locations are small, so they stay here as code.

// Dealership / gallery locations — all in İstanbul (real district coordinates).
const List<GalleryLocation> _galleryLocations = [
  GalleryLocation(
    id: 'loc-maslak',
    name: 'Anıl Galeri Maslak',
    city: 'İstanbul',
    address: 'Maslak, Sarıyer',
    latitude: 41.1106,
    longitude: 29.0203,
  ),
  GalleryLocation(
    id: 'loc-kadikoy',
    name: 'Anıl Galeri Kadıköy',
    city: 'İstanbul',
    address: 'Kadıköy',
    latitude: 40.9904,
    longitude: 29.0270,
  ),
  GalleryLocation(
    id: 'loc-besiktas',
    name: 'Anıl Galeri Beşiktaş',
    city: 'İstanbul',
    address: 'Beşiktaş',
    latitude: 41.0426,
    longitude: 29.0096,
  ),
  GalleryLocation(
    id: 'loc-umraniye',
    name: 'Anıl Galeri Ümraniye',
    city: 'İstanbul',
    address: 'Ümraniye',
    latitude: 41.0166,
    longitude: 29.1244,
  ),
];

// =============================================================================
// LOGIN
// =============================================================================

class LoginScreen extends StatefulWidget {
  const LoginScreen({super.key});

  @override
  State<LoginScreen> createState() => _LoginScreenState();
}

class _LoginScreenState extends State<LoginScreen> {
  final AuthService _authService = AuthService();
  final TextEditingController _emailController =
      TextEditingController(text: 'user@anilgaleri.com');
  final TextEditingController _passwordController =
      TextEditingController(text: '123456');
  bool _loading = false;
  String? _error;

  Future<void> _login() async {
    setState(() {
      _loading = true;
      _error = null;
    });

    try {
      final user =
          await _authService.login(_emailController.text, _passwordController.text);

      if (!mounted) return;
      setState(() => _loading = false);

      if (user == null) {
        setState(() => _error = tr('Please enter email and password.'));
        return;
      }

      Navigator.of(context).pushReplacement(
        LuxuryPageRoute(child: MainShell(user: user)),
      );
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _loading = false;
        _error = 'Login error: $e';
      });
    }
  }

  @override
  void dispose() {
    _emailController.dispose();
    _passwordController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: SafeArea(
        child: Center(
          child: SingleChildScrollView(
            padding: const EdgeInsets.all(24),
            child: ConstrainedBox(
              constraints: const BoxConstraints(maxWidth: 430),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  const Icon(Icons.directions_car_filled,
                      color: AppColors.gold, size: 72),
                  const SizedBox(height: 16),
                  const Text('Anıl Galeri',
                      textAlign: TextAlign.center,
                      style: TextStyle(fontSize: 34, fontWeight: FontWeight.w900)),
                  const SizedBox(height: 40),
                  TextField(
                    controller: _emailController,
                    keyboardType: TextInputType.emailAddress,
                    decoration: InputDecoration(
                      labelText: tr('Email'),
                      filled: true,
                      prefixIcon: const Icon(Icons.email_outlined),
                      border: const OutlineInputBorder(
                          borderRadius: BorderRadius.all(Radius.circular(18))),
                    ),
                  ),
                  const SizedBox(height: 14),
                  TextField(
                    controller: _passwordController,
                    obscureText: true,
                    decoration: InputDecoration(
                      labelText: tr('Password'),
                      filled: true,
                      prefixIcon: const Icon(Icons.lock_outline),
                      border: const OutlineInputBorder(
                          borderRadius: BorderRadius.all(Radius.circular(18))),
                    ),
                  ),
                  if (_error != null) ...[
                    const SizedBox(height: 10),
                    Text(_error!, style: const TextStyle(color: AppColors.red)),
                  ],
                  const SizedBox(height: 24),
                  FilledButton(
                    onPressed: _loading
                        ? null
                        : () {
                            AppHaptics.light();
                            _login();
                          },
                    style: FilledButton.styleFrom(
                      backgroundColor: AppColors.gold,
                      foregroundColor: Colors.black,
                      padding: const EdgeInsets.symmetric(vertical: 16),
                      shape: RoundedRectangleBorder(
                          borderRadius: BorderRadius.circular(18)),
                    ),
                    child: _loading
                        ? const SizedBox(
                            height: 20,
                            width: 20,
                            child: CircularProgressIndicator(strokeWidth: 2))
                        : Text(tr('Login'),
                            style: const TextStyle(fontWeight: FontWeight.bold)),
                  ),
                ],
              ),
            ),
          ),
        ),
      ),
    );
  }
}

// =============================================================================
// MAIN SHELL
// =============================================================================

class MainShell extends StatefulWidget {
  final AppUser user;
  const MainShell({super.key, required this.user});

  @override
  State<MainShell> createState() => _MainShellState();
}

class _MainShellState extends State<MainShell> {
  int _index = 0;

  @override
  Widget build(BuildContext context) {
    final pages = [
      BrowseScreen(user: widget.user),
      const LocationsScreen(),
      SettingsScreen(user: widget.user),
    ];

    return Scaffold(
      body: IndexedStack(index: _index, children: pages),
      bottomNavigationBar: ListenableBuilder(
        listenable: VehicleService.instance,
        builder: (context, _) {
          return NavigationBar(
            selectedIndex: _index,
            onDestinationSelected: (i) {
              AppHaptics.light();
              setState(() => _index = i);
            },
            backgroundColor: AppColors.card,
            indicatorColor: AppColors.gold,
            destinations: [
              NavigationDestination(
                  icon: const Icon(Icons.directions_car_outlined),
                  selectedIcon:
                      const Icon(Icons.directions_car, color: Colors.black),
                  label: tr('Browse')),
              NavigationDestination(
                  icon: const Icon(Icons.place_outlined),
                  selectedIcon: const Icon(Icons.place, color: Colors.black),
                  label: tr('Locations')),
              NavigationDestination(
                  icon: const Icon(Icons.settings_outlined),
                  selectedIcon: const Icon(Icons.settings, color: Colors.black),
                  label: tr('Settings')),
            ],
          );
        },
      ),
    );
  }
}

// =============================================================================
// BROWSE
// =============================================================================

class BrowseScreen extends StatefulWidget {
  final AppUser user;
  const BrowseScreen({super.key, required this.user});

  @override
  State<BrowseScreen> createState() => _BrowseScreenState();
}

class _BrowseScreenState extends State<BrowseScreen> {
  final VehicleService _service = VehicleService.instance;
  final TextEditingController _searchController = TextEditingController();

  VehicleFilter _filter = VehicleFilter();
  SortOption _sort = SortOption.priceAsc;
  String _query = '';
  static const int _pageSize = 10;
  int _visibleCount = _pageSize;

  @override
  void initState() {
    super.initState();
    _filter.locationId = AppSettings.instance.preferredLocationId;
    _service.ensureLoaded();
  }

  @override
  void dispose() {
    _searchController.dispose();
    super.dispose();
  }

  List<Vehicle> _applyPipeline(List<Vehicle> source) {
    final result = source
        .where((v) => _filter.matches(v))
        .where((v) => v.matchesSearch(_query))
        .toList();

    switch (_sort) {
      case SortOption.priceAsc:
        result.sort((a, b) => a.price.compareTo(b.price));
        break;
      case SortOption.priceDesc:
        result.sort((a, b) => b.price.compareTo(a.price));
        break;
      case SortOption.yearDesc:
        result.sort((a, b) => b.year.compareTo(a.year));
        break;
      case SortOption.mileageAsc:
        result.sort((a, b) => a.mileage.compareTo(b.mileage));
        break;
    }
    return result;
  }

  Future<void> _openSortMenu() async {
    AppHaptics.light();
    final selected = await showModalBottomSheet<SortOption>(
      context: context,
      backgroundColor: AppColors.card,
      shape: const RoundedRectangleBorder(
          borderRadius: BorderRadius.vertical(top: Radius.circular(22))),
      builder: (_) => SafeArea(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: SortOption.values.map((opt) {
            return RadioListTile<SortOption>(
              value: opt,
              groupValue: _sort,
              activeColor: AppColors.gold,
              title: Text(tr(opt.label)),
              onChanged: (v) => Navigator.pop(context, v),
            );
          }).toList(),
        ),
      ),
    );
    if (selected != null) setState(() => _sort = selected);
  }

  void _openVehicle(Vehicle vehicle) {
    AppHaptics.light();
    Navigator.of(context)
        .push(LuxuryPageRoute(child: VehicleDetailScreen(vehicle: vehicle)));
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        backgroundColor: AppColors.background,
        title: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const Text('Anıl Galeri',
                style: TextStyle(fontWeight: FontWeight.w900)),
            Text(widget.user.isAdmin ? tr('Admin Panel') : tr('Premium Cars'),
                style: const TextStyle(fontSize: 12, color: AppColors.muted)),
          ],
        ),
        actions: [
          IconButton(
              tooltip: tr('Sort'),
              onPressed: _openSortMenu,
              icon: const Icon(Icons.sort)),
          if (widget.user.isAdmin)
            IconButton(
              tooltip: tr('Manage Vehicles'),
              onPressed: () {
                AppHaptics.light();
                Navigator.of(context)
                    .push(LuxuryPageRoute(child: const AdminScreen()));
              },
              icon: const Icon(Icons.admin_panel_settings),
            ),
        ],
      ),
      body: ListenableBuilder(
        listenable: _service,
        builder: (context, _) {
          if (_service.isLoading) return const LuxuryHomeSkeleton();
          if (_service.error != null) {
            return ErrorView(
                error: _service.error!,
                onRetry: () => _service.ensureLoaded(force: true));
          }

          final all = _service.vehicles;
          // One card per model. If the same model sits in a gallery and the
          // warehouse, keep the gallery copy as the representative so the card
          // reads "Available now"; the detail page still offers pre-order.
          final byModel = <String, Vehicle>{};
          for (final v in all) {
            final key = '${v.brand}|${v.model}|${v.trimPackage}';
            final existing = byModel[key];
            if (existing == null) {
              byModel[key] = v;
            } else if (existing.locationId.trim().isEmpty &&
                v.locationId.trim().isNotEmpty) {
              byModel[key] = v;
            }
          }
          final unique = byModel.values.toList();
          final hotDeals = unique.where((v) => v.isHotDeal).toList();
          final filtered = _applyPipeline(unique);
          final visible = filtered.take(_visibleCount).toList();

          return RefreshIndicator(
            onRefresh: () => _service.ensureLoaded(force: true),
            color: AppColors.gold,
            child: ListView(
              padding: const EdgeInsets.all(14),
              children: [
                TextField(
                  controller: _searchController,
                  onChanged: (v) => setState(() {
                    _query = v;
                    _visibleCount = _pageSize;
                  }),
                  decoration: InputDecoration(
                    hintText: tr('Search brand or model...'),
                    filled: true,
                    fillColor: AppColors.card,
                    prefixIcon: const Icon(Icons.search),
                    suffixIcon: _query.isEmpty
                        ? null
                        : IconButton(
                            icon: const Icon(Icons.close),
                            onPressed: () {
                              _searchController.clear();
                              setState(() {
                                _query = '';
                                _visibleCount = _pageSize;
                              });
                            },
                          ),
                    border: OutlineInputBorder(
                        borderRadius: BorderRadius.circular(16),
                        borderSide: BorderSide.none),
                  ),
                ),
                const SizedBox(height: 20),
                Text(tr('Featured Deals'),
                    style: const TextStyle(
                        fontSize: 18, fontWeight: FontWeight.w900)),
                const SizedBox(height: 12),
                SizedBox(
                  height: 205,
                  child: hotDeals.isEmpty
                      ? Center(child: Text(tr('No hot deals found.')))
                      : ListView.separated(
                          scrollDirection: Axis.horizontal,
                          itemCount: hotDeals.length,
                          separatorBuilder: (_, __) =>
                              const SizedBox(width: 12),
                          itemBuilder: (context, index) => FeaturedDealCard(
                            vehicle: hotDeals[index],
                            onTap: () => _openVehicle(hotDeals[index]),
                          ),
                        ),
                ),
                const SizedBox(height: 28),
                Row(
                  children: [
                    Text(tr('Available Inventory'),
                        style: const TextStyle(
                            fontSize: 18, fontWeight: FontWeight.w900)),
                    const Spacer(),
                    Text('${filtered.length} ${tr('Cars')}',
                        style: const TextStyle(color: AppColors.muted)),
                  ],
                ),
                const SizedBox(height: 14),
                if (visible.isEmpty)
                  Padding(
                    padding: const EdgeInsets.only(top: 40, bottom: 20),
                    child: Center(
                        child: Text(
                            tr('No vehicles found. Try changing filters.'))),
                  )
                else
                  ...visible.map(
                    (vehicle) => Padding(
                      padding: const EdgeInsets.only(bottom: 16),
                      child: VehicleCard(
                          vehicle: vehicle, onTap: () => _openVehicle(vehicle)),
                    ),
                  ),
                if (_visibleCount < filtered.length)
                  Padding(
                    padding: const EdgeInsets.only(bottom: 12),
                    child: OutlinedButton(
                      onPressed: () {
                        AppHaptics.light();
                        setState(() => _visibleCount += _pageSize);
                      },
                      style: OutlinedButton.styleFrom(
                        side: const BorderSide(color: AppColors.gold),
                        padding: const EdgeInsets.symmetric(vertical: 14),
                      ),
                      child: Text(tr('Load more'),
                          style: const TextStyle(color: AppColors.gold)),
                    ),
                  ),
                const SizedBox(height: 80),
              ],
            ),
          );
        },
      ),
    );
  }
}

// =============================================================================
// GALLERY INVENTORY (opened from the Locations map — full filters here)
// =============================================================================

class GalleryInventoryScreen extends StatefulWidget {
  final String galleryId;
  const GalleryInventoryScreen({super.key, required this.galleryId});

  @override
  State<GalleryInventoryScreen> createState() => _GalleryInventoryScreenState();
}

class _GalleryInventoryScreenState extends State<GalleryInventoryScreen> {
  final VehicleService _service = VehicleService.instance;
  final TextEditingController _searchController = TextEditingController();

  VehicleFilter _filter = VehicleFilter();
  SortOption _sort = SortOption.priceAsc;
  String _query = '';
  static const int _pageSize = 10;
  int _visibleCount = _pageSize;

  @override
  void dispose() {
    _searchController.dispose();
    super.dispose();
  }

  List<Vehicle> _applyPipeline(List<Vehicle> source) {
    final result = source
        .where((v) => _filter.matches(v))
        .where((v) => v.matchesSearch(_query))
        .toList();
    switch (_sort) {
      case SortOption.priceAsc:
        result.sort((a, b) => a.price.compareTo(b.price));
        break;
      case SortOption.priceDesc:
        result.sort((a, b) => b.price.compareTo(a.price));
        break;
      case SortOption.yearDesc:
        result.sort((a, b) => b.year.compareTo(a.year));
        break;
      case SortOption.mileageAsc:
        result.sort((a, b) => a.mileage.compareTo(b.mileage));
        break;
    }
    return result;
  }

  Future<void> _openFilters() async {
    AppHaptics.light();
    final result = await showModalBottomSheet<VehicleFilter>(
      context: context,
      isScrollControlled: true,
      backgroundColor: Colors.transparent,
      builder: (_) => FilterSheet(initialFilter: _filter),
    );
    if (result != null) {
      setState(() {
        _filter = result;
        _visibleCount = _pageSize;
      });
    }
  }

  void _setBodyType(BodyType type) {
    setState(() {
      _filter.bodyType = _filter.bodyType == type ? null : type;
      _visibleCount = _pageSize;
    });
  }

  void _setFuelType(FuelType type) {
    setState(() {
      _filter.fuelType = _filter.fuelType == type ? null : type;
      _visibleCount = _pageSize;
    });
  }

  void _setPerformance() {
    setState(() {
      _filter.showPerformanceOnly = !_filter.showPerformanceOnly;
      _visibleCount = _pageSize;
    });
  }

  Future<void> _openSortMenu() async {
    AppHaptics.light();
    final selected = await showModalBottomSheet<SortOption>(
      context: context,
      backgroundColor: AppColors.card,
      shape: const RoundedRectangleBorder(
          borderRadius: BorderRadius.vertical(top: Radius.circular(22))),
      builder: (_) => SafeArea(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: SortOption.values.map((opt) {
            return RadioListTile<SortOption>(
              value: opt,
              groupValue: _sort,
              activeColor: AppColors.gold,
              title: Text(tr(opt.label)),
              onChanged: (v) => Navigator.pop(context, v),
            );
          }).toList(),
        ),
      ),
    );
    if (selected != null) setState(() => _sort = selected);
  }

  void _openVehicle(Vehicle vehicle) {
    AppHaptics.light();
    Navigator.of(context)
        .push(LuxuryPageRoute(child: VehicleDetailScreen(vehicle: vehicle, fromLocations: true)));
  }

  @override
  Widget build(BuildContext context) {
    final gallery = _service.locationById(widget.galleryId);
    return Scaffold(
      appBar: AppBar(
        backgroundColor: AppColors.background,
        title: Text(widget.galleryId.trim().isEmpty
            ? tr('Warehouse')
            : (gallery?.name ?? tr('Gallery'))),
        actions: [
          IconButton(
              tooltip: tr('Sort'),
              onPressed: _openSortMenu,
              icon: const Icon(Icons.sort)),
        ],
      ),
      body: ListenableBuilder(
        listenable: _service,
        builder: (context, _) {
          if (_service.isLoading) return const LuxuryHomeSkeleton();
          final scoped = _service.vehicles
              .where((v) => v.locationId == widget.galleryId)
              .toList();
          final filtered = _applyPipeline(scoped);
          final visible = filtered.take(_visibleCount).toList();

          return ListView(
            padding: const EdgeInsets.all(14),
            children: [
              TextField(
                controller: _searchController,
                onChanged: (v) => setState(() {
                  _query = v;
                  _visibleCount = _pageSize;
                }),
                decoration: InputDecoration(
                  hintText: tr('Search brand or model...'),
                  filled: true,
                  fillColor: AppColors.card,
                  prefixIcon: const Icon(Icons.search),
                  suffixIcon: _query.isEmpty
                      ? null
                      : IconButton(
                          icon: const Icon(Icons.close),
                          onPressed: () {
                            _searchController.clear();
                            setState(() {
                              _query = '';
                              _visibleCount = _pageSize;
                            });
                          },
                        ),
                  border: OutlineInputBorder(
                      borderRadius: BorderRadius.circular(16),
                      borderSide: BorderSide.none),
                ),
              ),
              const SizedBox(height: 14),
              SingleChildScrollView(
                scrollDirection: Axis.horizontal,
                child: Row(
                  children: [
                    FilterButton(
                        icon: Icons.tune,
                        label: tr('Filters'),
                        selected: false,
                        onTap: _openFilters),
                    FilterButton(
                        icon: Icons.flash_on,
                        label: tr('Performance'),
                        selected: _filter.showPerformanceOnly,
                        onTap: _setPerformance),
                    FilterButton(
                        icon: Icons.directions_car,
                        label: tr('SUV'),
                        selected: _filter.bodyType == BodyType.suv,
                        onTap: () => _setBodyType(BodyType.suv)),
                    FilterButton(
                        icon: Icons.local_taxi,
                        label: tr('Sedan'),
                        selected: _filter.bodyType == BodyType.sedan,
                        onTap: () => _setBodyType(BodyType.sedan)),
                    FilterButton(
                        icon: Icons.bolt,
                        label: tr('Electric'),
                        selected: _filter.fuelType == FuelType.electric,
                        onTap: () => _setFuelType(FuelType.electric)),
                  ],
                ),
              ),
              const SizedBox(height: 16),
              Row(
                children: [
                  Text(tr('Available Inventory'),
                      style: const TextStyle(
                          fontSize: 18, fontWeight: FontWeight.w900)),
                  const Spacer(),
                  Text('${filtered.length} ${tr('Cars')}',
                      style: const TextStyle(color: AppColors.muted)),
                ],
              ),
              const SizedBox(height: 14),
              if (visible.isEmpty)
                Padding(
                  padding: const EdgeInsets.only(top: 60),
                  child: Center(
                      child: Text(
                          tr('No vehicles found. Try changing filters.'))),
                )
              else
                ...visible.map(
                  (vehicle) => Padding(
                    padding: const EdgeInsets.only(bottom: 16),
                    child: VehicleCard(
                        vehicle: vehicle, onTap: () => _openVehicle(vehicle)),
                  ),
                ),
              if (_visibleCount < filtered.length)
                Padding(
                  padding: const EdgeInsets.only(bottom: 12),
                  child: OutlinedButton(
                    onPressed: () {
                      AppHaptics.light();
                      setState(() => _visibleCount += _pageSize);
                    },
                    style: OutlinedButton.styleFrom(
                      side: const BorderSide(color: AppColors.gold),
                      padding: const EdgeInsets.symmetric(vertical: 14),
                    ),
                    child: Text(tr('Load more'),
                        style: const TextStyle(color: AppColors.gold)),
                  ),
                ),
              const SizedBox(height: 40),
            ],
          );
        },
      ),
    );
  }
}

// =============================================================================
// SKELETONS / ERROR
// =============================================================================

class LuxuryHomeSkeleton extends StatefulWidget {
  const LuxuryHomeSkeleton({super.key});

  @override
  State<LuxuryHomeSkeleton> createState() => _LuxuryHomeSkeletonState();
}

class _LuxuryHomeSkeletonState extends State<LuxuryHomeSkeleton>
    with SingleTickerProviderStateMixin {
  late final AnimationController _controller;

  @override
  void initState() {
    super.initState();
    _controller = AnimationController(
        vsync: this, duration: const Duration(milliseconds: 1450))
      ..repeat();
  }

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return AnimatedBuilder(
      animation: _controller,
      builder: (context, child) {
        return ListView(
          padding: const EdgeInsets.all(14),
          children: [
            _SkeletonBox(width: 140, height: 22, shimmerValue: _controller.value),
            const SizedBox(height: 12),
            _SkeletonBox(
                width: 310, height: 205, radius: 18, shimmerValue: _controller.value),
            const SizedBox(height: 28),
            Row(
              children: [
                _SkeletonBox(width: 190, height: 22, shimmerValue: _controller.value),
                const Spacer(),
                _SkeletonBox(width: 54, height: 18, shimmerValue: _controller.value),
              ],
            ),
            const SizedBox(height: 14),
            Row(
              children: List.generate(
                4,
                (index) => Padding(
                  padding: const EdgeInsets.only(right: 10),
                  child: _SkeletonBox(
                      width: index == 0 ? 98 : 86,
                      height: 44,
                      radius: 24,
                      shimmerValue: _controller.value),
                ),
              ),
            ),
            const SizedBox(height: 18),
            _SkeletonBox(
                width: double.infinity,
                height: 390,
                radius: 18,
                shimmerValue: _controller.value),
            const SizedBox(height: 16),
            _SkeletonBox(
                width: double.infinity,
                height: 390,
                radius: 18,
                shimmerValue: _controller.value),
          ],
        );
      },
    );
  }
}

class LuxuryImageSkeleton extends StatefulWidget {
  const LuxuryImageSkeleton({super.key});

  @override
  State<LuxuryImageSkeleton> createState() => _LuxuryImageSkeletonState();
}

class _LuxuryImageSkeletonState extends State<LuxuryImageSkeleton>
    with SingleTickerProviderStateMixin {
  late final AnimationController _controller;

  @override
  void initState() {
    super.initState();
    _controller = AnimationController(
        vsync: this, duration: const Duration(milliseconds: 1450))
      ..repeat();
  }

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return AnimatedBuilder(
      animation: _controller,
      builder: (context, child) => _SkeletonBox(
        width: double.infinity,
        height: double.infinity,
        radius: 0,
        shimmerValue: _controller.value,
      ),
    );
  }
}

class _SkeletonBox extends StatelessWidget {
  final double width;
  final double height;
  final double radius;
  final double shimmerValue;

  const _SkeletonBox(
      {required this.width,
      required this.height,
      this.radius = 10,
      required this.shimmerValue});

  @override
  Widget build(BuildContext context) {
    return Container(
      width: width,
      height: height,
      decoration: BoxDecoration(
        borderRadius: BorderRadius.circular(radius),
        gradient: LinearGradient(
          begin: Alignment(-1.2 + shimmerValue * 2.4, 0),
          end: Alignment(-0.2 + shimmerValue * 2.4, 0),
          colors: const [
            Color(0xFF1E1E24),
            Color(0xFF30303A),
            Color(0xFF1E1E24),
          ],
        ),
      ),
    );
  }
}

class ErrorView extends StatelessWidget {
  final String error;
  final VoidCallback onRetry;

  const ErrorView({super.key, required this.error, required this.onRetry});

  @override
  Widget build(BuildContext context) {
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(24),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            const Icon(Icons.error_outline, color: AppColors.red, size: 48),
            const SizedBox(height: 16),
            Text(tr('Vehicle loading error'),
                style: const TextStyle(fontSize: 20, fontWeight: FontWeight.bold)),
            const SizedBox(height: 8),
            Text(error,
                textAlign: TextAlign.center,
                style: const TextStyle(color: AppColors.muted)),
            const SizedBox(height: 18),
            FilledButton(onPressed: onRetry, child: Text(tr('Retry'))),
          ],
        ),
      ),
    );
  }
}

// =============================================================================
// CARDS
// =============================================================================

class FeaturedDealCard extends StatelessWidget {
  final Vehicle vehicle;
  final VoidCallback onTap;

  const FeaturedDealCard({super.key, required this.vehicle, required this.onTap});

  @override
  Widget build(BuildContext context) {
    return GestureDetector(
      onTap: () {
        AppHaptics.light();
        onTap();
      },
      child: Container(
        width: 310,
        clipBehavior: Clip.antiAlias,
        decoration: BoxDecoration(
            borderRadius: BorderRadius.circular(18), color: AppColors.card),
        child: Stack(
          fit: StackFit.expand,
          children: [
            NetworkCarImage(url: vehicle.coverImage),
            Container(
              decoration: BoxDecoration(
                gradient: LinearGradient(
                  begin: Alignment.topCenter,
                  end: Alignment.bottomCenter,
                  colors: [Colors.transparent, Colors.black.withOpacity(0.85)],
                ),
              ),
            ),
            Padding(
              padding: const EdgeInsets.all(16),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                mainAxisAlignment: MainAxisAlignment.end,
                children: [
                  Container(
                    padding:
                        const EdgeInsets.symmetric(horizontal: 8, vertical: 5),
                    decoration: BoxDecoration(
                        color: AppColors.gold,
                        borderRadius: BorderRadius.circular(6)),
                    child: Text(tr('HOT DEAL'),
                        style: const TextStyle(
                            color: Colors.black,
                            fontSize: 11,
                            fontWeight: FontWeight.bold)),
                  ),
                  const SizedBox(height: 8),
                  Row(
                    children: [
                      Expanded(
                          child: Text(vehicle.fullName,
                              style: const TextStyle(
                                  fontSize: 18, fontWeight: FontWeight.w900))),
                      Column(
                        crossAxisAlignment: CrossAxisAlignment.end,
                        children: [
                          if (vehicle.isHotDeal)
                            Text(vehicle.formattedPrice,
                                style: const TextStyle(
                                    color: Colors.white54,
                                    fontSize: 11,
                                    decoration: TextDecoration.lineThrough)),
                          Text(vehicle.formattedSalePrice,
                              style: const TextStyle(
                                  color: AppColors.gold,
                                  fontWeight: FontWeight.bold)),
                        ],
                      ),
                    ],
                  ),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class FeaturedDealCardCompact extends StatelessWidget {
  final Vehicle vehicle;
  final VoidCallback onTap;
  const FeaturedDealCardCompact(
      {super.key, required this.vehicle, required this.onTap});

  @override
  Widget build(BuildContext context) {
    return GestureDetector(
      onTap: onTap,
      child: Container(
        width: 260,
        clipBehavior: Clip.antiAlias,
        decoration: BoxDecoration(
            borderRadius: BorderRadius.circular(18), color: AppColors.card),
        child: Stack(
          fit: StackFit.expand,
          children: [
            NetworkCarImage(url: vehicle.coverImage),
            Container(
              decoration: BoxDecoration(
                gradient: LinearGradient(
                  begin: Alignment.topCenter,
                  end: Alignment.bottomCenter,
                  colors: [Colors.transparent, Colors.black.withOpacity(0.85)],
                ),
              ),
            ),
            Padding(
              padding: const EdgeInsets.all(16),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                mainAxisAlignment: MainAxisAlignment.end,
                children: [
                  Text(vehicle.fullName,
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: const TextStyle(
                          fontSize: 16, fontWeight: FontWeight.w900)),
                  const SizedBox(height: 4),
                  Text(vehicle.formattedPrice,
                      style: const TextStyle(
                          color: AppColors.gold, fontWeight: FontWeight.bold)),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class VehicleCard extends StatelessWidget {
  final Vehicle vehicle;
  final VoidCallback onTap;

  const VehicleCard({super.key, required this.vehicle, required this.onTap});

  @override
  Widget build(BuildContext context) {
    final service = VehicleService.instance;
    return ListenableBuilder(
      listenable: service,
      builder: (context, _) {
        return GestureDetector(
          onTap: () {
            AppHaptics.light();
            onTap();
          },
          child: Container(
            decoration: BoxDecoration(
              color: AppColors.card,
              borderRadius: BorderRadius.circular(18),
              border: Border.all(color: Colors.white.withOpacity(0.08)),
            ),
            clipBehavior: Clip.antiAlias,
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Stack(
                  children: [
                    SizedBox(
                      height: 230,
                      width: double.infinity,
                      child: Hero(
                        tag: 'vehicle-image-${vehicle.id}',
                        child: NetworkCarImage(url: vehicle.coverImage),
                      ),
                    ),
                    Positioned(
                      top: 14,
                      left: 14,
                      child: Container(
                        padding: const EdgeInsets.symmetric(
                            horizontal: 8, vertical: 5),
                        decoration: BoxDecoration(
                            color: AppColors.gold,
                            borderRadius: BorderRadius.circular(6)),
                        child: Text(
                            vehicle.isHotDeal
                                ? tr('Hot Deal')
                                : tr('Great Price'),
                            style: const TextStyle(
                                color: Colors.black,
                                fontSize: 12,
                                fontWeight: FontWeight.bold)),
                      ),
                    ),
                  ],
                ),
                Padding(
                  padding: const EdgeInsets.all(16),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(vehicle.fullName,
                          style: const TextStyle(
                              fontSize: 20, fontWeight: FontWeight.w900)),
                      const SizedBox(height: 10),
                      Row(
                        children: [
                          AvailabilityBadge(vehicle: vehicle),
                        ],
                      ),
                      const SizedBox(height: 12),
                      Wrap(
                        spacing: 8,
                        runSpacing: 8,
                        children: [
                          SmallInfoChip(
                              icon: Icons.calendar_today,
                              label: '${vehicle.year}'),
                          SmallInfoChip(
                              icon: Icons.speed,
                              label: vehicle.formattedMileage),
                          SmallInfoChip(
                              icon: Icons.local_gas_station,
                              label: vehicle.fuelType.localizedLabel),
                        ],
                      ),
                      const SizedBox(height: 18),
                      if (vehicle.isHotDeal) ...[
                        Row(
                          crossAxisAlignment: CrossAxisAlignment.end,
                          children: [
                            Text(vehicle.formattedSalePrice,
                                style: const TextStyle(
                                    color: AppColors.gold,
                                    fontSize: 22,
                                    fontWeight: FontWeight.w900)),
                            const SizedBox(width: 8),
                            Padding(
                              padding: const EdgeInsets.only(bottom: 3),
                              child: Text(vehicle.formattedPrice,
                                  style: const TextStyle(
                                      color: AppColors.muted,
                                      fontSize: 14,
                                      decoration:
                                          TextDecoration.lineThrough)),
                            ),
                          ],
                        ),
                        Text(
                            '${tr('You save')} ${vehicle.formattedSavings} (10%)',
                            style: const TextStyle(
                                color: AppColors.green,
                                fontSize: 12,
                                fontWeight: FontWeight.bold)),
                      ] else
                        Text(vehicle.formattedPrice,
                            style: const TextStyle(
                                color: AppColors.gold,
                                fontSize: 22,
                                fontWeight: FontWeight.w900)),
                    ],
                  ),
                ),
              ],
            ),
          ),
        );
      },
    );
  }
}

class NetworkCarImage extends StatelessWidget {
  final String url;
  const NetworkCarImage({super.key, required this.url});

  @override
  Widget build(BuildContext context) {
    if (url.isEmpty) {
      return const ColoredBox(
          color: AppColors.cardLight,
          child: Center(child: Icon(Icons.directions_car, size: 60)));
    }
    // UPGRADE: replace Image.network with CachedNetworkImage
    // (cached_network_image) to cache on disk and avoid re-downloads.
    return Image.network(
      url,
      fit: BoxFit.cover,
      loadingBuilder: (context, child, loadingProgress) {
        if (loadingProgress == null) return child;
        return const LuxuryImageSkeleton();
      },
      errorBuilder: (context, error, stackTrace) {
        return const ColoredBox(
          color: AppColors.cardLight,
          child: Center(
              child: Icon(Icons.directions_car, size: 60, color: AppColors.gold)),
        );
      },
    );
  }
}

class FilterButton extends StatelessWidget {
  final IconData icon;
  final String label;
  final bool selected;
  final VoidCallback onTap;

  const FilterButton(
      {super.key,
      required this.icon,
      required this.label,
      required this.selected,
      required this.onTap});

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(right: 10),
      child: InkWell(
        onTap: () {
          AppHaptics.light();
          onTap();
        },
        borderRadius: BorderRadius.circular(24),
        child: Container(
          padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
          decoration: BoxDecoration(
            color: selected ? AppColors.gold : AppColors.cardLight,
            borderRadius: BorderRadius.circular(24),
          ),
          child: Row(
            children: [
              Icon(icon, size: 18, color: selected ? Colors.black : Colors.white),
              const SizedBox(width: 8),
              Text(label,
                  style: TextStyle(
                      color: selected ? Colors.black : Colors.white,
                      fontWeight: FontWeight.w700)),
            ],
          ),
        ),
      ),
    );
  }
}

class SmallInfoChip extends StatelessWidget {
  final IconData icon;
  final String label;
  const SmallInfoChip({super.key, required this.icon, required this.label});

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 8),
      decoration: BoxDecoration(
          color: AppColors.cardLight, borderRadius: BorderRadius.circular(10)),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(icon, size: 14, color: AppColors.muted),
          const SizedBox(width: 6),
          Text(label, style: const TextStyle(fontSize: 12)),
        ],
      ),
    );
  }
}

class AvailabilityBadge extends StatelessWidget {
  final Vehicle vehicle;
  const AvailabilityBadge({super.key, required this.vehicle});

  @override
  Widget build(BuildContext context) {
    // A car with no gallery (warehouse) is shown to customers as pre-order.
    final isPreOrder = vehicle.locationId.trim().isEmpty;
    final Color color;
    final IconData icon;
    final String label;
    if (isPreOrder) {
      color = AppColors.gold;
      icon = Icons.schedule;
      label = tr('Pre-order');
    } else {
      color = AppColors.green;
      icon = Icons.check_circle;
      label = tr('Available now');
    }
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 9, vertical: 5),
      decoration: BoxDecoration(
        color: color.withOpacity(0.16),
        borderRadius: BorderRadius.circular(8),
        border: Border.all(color: color.withOpacity(0.5)),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(icon, size: 13, color: color),
          const SizedBox(width: 5),
          Text(label,
              style: TextStyle(
                  color: color, fontSize: 11, fontWeight: FontWeight.bold)),
        ],
      ),
    );
  }
}

// =============================================================================
// FILTER SHEET
// =============================================================================

class FilterSheet extends StatefulWidget {
  final VehicleFilter initialFilter;
  const FilterSheet({super.key, required this.initialFilter});

  @override
  State<FilterSheet> createState() => _FilterSheetState();
}

class _FilterSheetState extends State<FilterSheet> {
  late VehicleFilter filter;

  @override
  void initState() {
    super.initState();
    filter = widget.initialFilter.copy();
  }

  @override
  Widget build(BuildContext context) {
    return DraggableScrollableSheet(
      expand: false,
      initialChildSize: 0.88,
      maxChildSize: 0.95,
      minChildSize: 0.5,
      builder: (context, controller) {
        return Container(
          padding: const EdgeInsets.fromLTRB(24, 14, 24, 24),
          decoration: const BoxDecoration(
            color: Colors.white,
            borderRadius: BorderRadius.vertical(top: Radius.circular(28)),
          ),
          child: ListView(
            controller: controller,
            children: [
              Center(
                  child: Container(
                      width: 48,
                      height: 5,
                      decoration: BoxDecoration(
                          color: Colors.black12,
                          borderRadius: BorderRadius.circular(10)))),
              const SizedBox(height: 24),
              Row(
                children: [
                  Text(tr('Filters'),
                      style: const TextStyle(
                          color: Colors.black,
                          fontSize: 24,
                          fontWeight: FontWeight.w900)),
                  const Spacer(),
                  IconButton.filledTonal(
                    onPressed: () {
                      AppHaptics.light();
                      Navigator.pop(context);
                    },
                    icon: const Icon(Icons.close),
                    color: Colors.black,
                  ),
                ],
              ),
              const SizedBox(height: 20),
              const FilterLabel('BRAND'),
              Builder(builder: (context) {
                final brands = (VehicleService.instance.vehicles
                        .map((v) => v.brand)
                        .toSet()
                        .toList())
                  ..sort();
                final current = filter.brand ?? 'All';
                return DropdownButtonFormField<String>(
                  value: brands.contains(current) || current == 'All'
                      ? current
                      : 'All',
                  dropdownColor: Colors.white,
                  isExpanded: true,
                  decoration: _lightInputDecoration(),
                  items: [
                    const DropdownMenuItem(
                        value: 'All',
                        child: Text('All Brands',
                            style: TextStyle(color: Colors.black))),
                    ...brands.map((b) => DropdownMenuItem(
                        value: b,
                        child: Text(b,
                            style: const TextStyle(color: Colors.black)))),
                  ],
                  onChanged: (value) {
                    AppHaptics.light();
                    setState(() => filter.brand = value == 'All' ? null : value);
                  },
                  style: const TextStyle(
                      color: Colors.black, fontWeight: FontWeight.w600),
                );
              }),
              const SizedBox(height: 28),
              Row(
                children: [
                  const FilterLabel('PRICE RANGE'),
                  const Spacer(),
                  Text(
                      '\$${filter.minPrice.round()} - \$${filter.maxPrice.round()}',
                      style: const TextStyle(
                          color: Colors.black, fontWeight: FontWeight.bold)),
                ],
              ),
              RangeSlider(
                values: RangeValues(filter.minPrice, filter.maxPrice),
                min: 10000,
                max: 300000,
                divisions: 29,
                activeColor: Colors.black,
                inactiveColor: Colors.black12,
                labels: RangeLabels('\$${filter.minPrice.round()}',
                    '\$${filter.maxPrice.round()}'),
                onChanged: (values) => setState(() {
                  filter.minPrice = values.start;
                  filter.maxPrice = values.end;
                }),
                onChangeEnd: (_) => AppHaptics.light(),
              ),
              const SizedBox(height: 22),
              Row(
                children: [
                  const FilterLabel('YEAR RANGE'),
                  const Spacer(),
                  Text('${filter.minYear} - ${filter.maxYear}',
                      style: const TextStyle(
                          color: Colors.black, fontWeight: FontWeight.bold)),
                ],
              ),
              RangeSlider(
                values: RangeValues(
                    filter.minYear.toDouble(), filter.maxYear.toDouble()),
                min: 2015,
                max: 2026,
                divisions: 11,
                activeColor: Colors.black,
                inactiveColor: Colors.black12,
                onChanged: (values) => setState(() {
                  filter.minYear = values.start.round();
                  filter.maxYear = values.end.round();
                }),
                onChangeEnd: (_) => AppHaptics.light(),
              ),
              const SizedBox(height: 22),
              const FilterLabel('TRANSMISSION'),
              Wrap(
                spacing: 8,
                runSpacing: 8,
                children: Transmission.values.map((transmission) {
                  final selected = filter.transmission == transmission;
                  return ChoiceChip(
                    selected: selected,
                    backgroundColor: const Color(0xFFEDEEF2),
                    selectedColor: Colors.black,
                    label: Text(transmission.localizedLabel,
                        style: TextStyle(
                            color: selected ? Colors.white : Colors.black,
                            fontWeight: FontWeight.w700)),
                    onSelected: (_) {
                      AppHaptics.light();
                      setState(() => filter.transmission =
                          selected ? null : transmission);
                    },
                  );
                }).toList(),
              ),
              const SizedBox(height: 22),
              const FilterLabel('FUEL TYPE'),
              Wrap(
                spacing: 8,
                runSpacing: 8,
                children: FuelType.values.map((fuel) {
                  final selected = filter.fuelType == fuel;
                  return ChoiceChip(
                    selected: selected,
                    backgroundColor: const Color(0xFFEDEEF2),
                    selectedColor: Colors.black,
                    label: Text(fuel.localizedLabel,
                        style: TextStyle(
                            color: selected ? Colors.white : Colors.black,
                            fontWeight: FontWeight.w700)),
                    onSelected: (_) {
                      AppHaptics.light();
                      setState(() => filter.fuelType = selected ? null : fuel);
                    },
                  );
                }).toList(),
              ),
              const SizedBox(height: 22),
              const FilterLabel('BODY TYPE'),
              Wrap(
                spacing: 8,
                runSpacing: 8,
                children: BodyType.values.map((body) {
                  final selected = filter.bodyType == body;
                  return ChoiceChip(
                    selected: selected,
                    backgroundColor: const Color(0xFFEDEEF2),
                    selectedColor: Colors.black,
                    label: Text(body.localizedLabel,
                        style: TextStyle(
                            color: selected ? Colors.white : Colors.black,
                            fontWeight: FontWeight.w700)),
                    onSelected: (_) {
                      AppHaptics.light();
                      setState(() => filter.bodyType = selected ? null : body);
                    },
                  );
                }).toList(),
              ),
              const SizedBox(height: 18),
              Container(
                decoration: BoxDecoration(
                  color: const Color(0xFFF1F2F5),
                  borderRadius: BorderRadius.circular(16),
                ),
                child: SwitchListTile(
                  value: filter.hideDamaged,
                  activeColor: Colors.black,
                  contentPadding:
                      const EdgeInsets.symmetric(horizontal: 16, vertical: 4),
                  shape: RoundedRectangleBorder(
                      borderRadius: BorderRadius.circular(16)),
                  secondary: const Icon(Icons.verified_outlined,
                      color: Colors.black54),
                  title: Text(tr('Hide Damaged / Painted Vehicles'),
                      style: const TextStyle(
                          color: Colors.black, fontWeight: FontWeight.w700)),
                  onChanged: (v) {
                    AppHaptics.light();
                    setState(() => filter.hideDamaged = v);
                  },
                ),
              ),
              const SizedBox(height: 30),
              FilledButton(
                onPressed: () {
                  AppHaptics.medium();
                  Navigator.pop(context, filter);
                },
                style: FilledButton.styleFrom(
                  backgroundColor: Colors.black,
                  padding: const EdgeInsets.symmetric(vertical: 18),
                  shape: RoundedRectangleBorder(
                      borderRadius: BorderRadius.circular(18)),
                ),
                child: Text(tr('Apply Filters'),
                    style: const TextStyle(
                        color: Colors.white, fontWeight: FontWeight.w900)),
              ),
            ],
          ),
        );
      },
    );
  }

  InputDecoration _lightInputDecoration() {
    return InputDecoration(
      filled: true,
      fillColor: const Color(0xFFF1F2F5),
      border: OutlineInputBorder(
          borderRadius: BorderRadius.circular(16), borderSide: BorderSide.none),
      contentPadding: const EdgeInsets.symmetric(horizontal: 16, vertical: 18),
    );
  }
}

class FilterLabel extends StatelessWidget {
  final String text;
  const FilterLabel(this.text, {super.key});

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 8),
      child: Text(text,
          style: const TextStyle(
              color: Color(0xFF6E6E80),
              fontWeight: FontWeight.bold,
              letterSpacing: 1.1)),
    );
  }
}

class FilterLabelDark extends StatelessWidget {
  final String text;
  const FilterLabelDark(this.text, {super.key});

  @override
  Widget build(BuildContext context) {
    return Text(text,
        style: const TextStyle(
            color: AppColors.muted,
            fontWeight: FontWeight.bold,
            letterSpacing: 1.1));
  }
}

// =============================================================================
// VEHICLE DETAIL
// =============================================================================

class VehicleDetailScreen extends StatefulWidget {
  final Vehicle vehicle;
  // false → opened from Browse (read-only, directs the user to Locations).
  // true  → opened from a Locations gallery/warehouse (scoped, actionable).
  final bool fromLocations;
  const VehicleDetailScreen(
      {super.key, required this.vehicle, this.fromLocations = false});

  @override
  State<VehicleDetailScreen> createState() => _VehicleDetailScreenState();
}

class _VehicleDetailScreenState extends State<VehicleDetailScreen> {
  final PageController _pageController = PageController();
  int _imageIndex = 0;

  @override
  void dispose() {
    _pageController.dispose();
    super.dispose();
  }

  // Spec cards adapt to the powertrain — no meaningless "0 cc" / "0.0 kWh".
  List<Widget> _specCards(Vehicle v) {
    final s = v.specs;
    final cards = <Widget>[
      SpecCard(
          icon: Icons.speed, title: tr('Top Speed'), value: '${s.topSpeed} km/h'),
      SpecCard(
          icon: Icons.bolt,
          title: tr('0-100 km/h'),
          value: '${s.zeroToHundred} sec'),
      SpecCard(icon: Icons.show_chart, title: tr('Power'), value: '${s.powerHp} HP'),
    ];

    switch (v.fuelType) {
      case FuelType.electric:
        cards.add(SpecCard(
            icon: Icons.battery_full,
            title: tr('Battery'),
            value: '${s.batteryKwh} kWh'));
        cards.add(SpecCard(
            icon: Icons.route, title: tr('Range'), value: '${s.rangeKm} km'));
        break;
      case FuelType.hybrid:
        cards.add(SpecCard(
            icon: Icons.local_gas_station,
            title: tr('Engine'),
            value: '${s.engineCc} cc'));
        cards.add(SpecCard(
            icon: Icons.battery_charging_full,
            title: tr('Battery'),
            value: '${s.batteryKwh} kWh'));
        if (s.rangeKm > 0) {
          cards.add(SpecCard(
              icon: Icons.route,
              title: tr('Electric Range'),
              value: '${s.rangeKm} km'));
        }
        break;
      case FuelType.petrol:
      case FuelType.diesel:
        cards.add(SpecCard(
            icon: Icons.local_gas_station,
            title: tr('Engine'),
            value: '${s.engineCc} cc'));
        cards.add(SpecCard(
            icon: Icons.sync, title: tr('Torque'), value: '${s.torque} Nm'));
        break;
    }

    cards.add(SpecCard(
        icon: Icons.settings_input_component,
        title: tr('Drivetrain'),
        value: s.drivetrain));
    cards.add(SpecCard(icon: Icons.palette, title: tr('Color'), value: s.color));
    return cards;
  }

  @override
  Widget build(BuildContext context) {
    final vehicle = widget.vehicle;
    final gallery =
        vehicle.galleryUrls.isEmpty ? [vehicle.coverImage] : vehicle.galleryUrls;

    return Scaffold(
      body: CustomScrollView(
        slivers: [
          SliverAppBar(
            expandedHeight: 320,
            pinned: true,
            stretch: true,
            backgroundColor: AppColors.background,
            flexibleSpace: FlexibleSpaceBar(
              collapseMode: CollapseMode.parallax,
              stretchModes: const [StretchMode.zoomBackground],
              background: Stack(
                fit: StackFit.expand,
                children: [
                  PageView.builder(
                    controller: _pageController,
                    itemCount: gallery.length,
                    onPageChanged: (i) => setState(() => _imageIndex = i),
                    itemBuilder: (context, i) {
                      final img = NetworkCarImage(url: gallery[i]);
                      if (i == 0) {
                        return Hero(
                            tag: 'vehicle-image-${vehicle.id}', child: img);
                      }
                      return img;
                    },
                  ),
                  if (gallery.length > 1)
                    Positioned(
                      bottom: 12,
                      left: 0,
                      right: 0,
                      child: Row(
                        mainAxisAlignment: MainAxisAlignment.center,
                        children: List.generate(gallery.length, (i) {
                          final active = i == _imageIndex;
                          return AnimatedContainer(
                            duration: const Duration(milliseconds: 250),
                            margin: const EdgeInsets.symmetric(horizontal: 3),
                            width: active ? 22 : 8,
                            height: 8,
                            decoration: BoxDecoration(
                              color: active
                                  ? AppColors.gold
                                  : Colors.white.withOpacity(0.5),
                              borderRadius: BorderRadius.circular(4),
                            ),
                          );
                        }),
                      ),
                    ),
                ],
              ),
            ),
          ),
          SliverToBoxAdapter(
            child: Padding(
              padding: const EdgeInsets.all(18),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(vehicle.fullName,
                      style: const TextStyle(
                          fontSize: 30, fontWeight: FontWeight.w900)),
                  const SizedBox(height: 8),
                  if (vehicle.isHotDeal) ...[
                    Row(
                      crossAxisAlignment: CrossAxisAlignment.end,
                      children: [
                        Text(vehicle.formattedSalePrice,
                            style: const TextStyle(
                                fontSize: 24,
                                fontWeight: FontWeight.w900,
                                color: AppColors.gold)),
                        const SizedBox(width: 10),
                        Padding(
                          padding: const EdgeInsets.only(bottom: 3),
                          child: Text(vehicle.formattedPrice,
                              style: const TextStyle(
                                  color: AppColors.muted,
                                  fontSize: 16,
                                  decoration: TextDecoration.lineThrough)),
                        ),
                      ],
                    ),
                    const SizedBox(height: 2),
                    Text('${tr('You save')} ${vehicle.formattedSavings} (10%)',
                        style: const TextStyle(
                            color: AppColors.green,
                            fontWeight: FontWeight.bold)),
                  ] else
                    Text(vehicle.formattedPrice,
                        style: const TextStyle(
                            fontSize: 24,
                            fontWeight: FontWeight.w900,
                            color: AppColors.gold)),
                  const SizedBox(height: 16),
                  _LocationPanel(
                      vehicle: vehicle,
                      scopeLocationId: widget.fromLocations
                          ? vehicle.locationId.trim()
                          : null),
                  const SizedBox(height: 24),
                  InkWell(
                    onTap: () {
                      AppHaptics.light();
                      Navigator.of(context).push(LuxuryPageRoute(
                          child: InspectionScreen(vehicle: vehicle)));
                    },
                    borderRadius: BorderRadius.circular(18),
                    child: Container(
                      padding: const EdgeInsets.all(18),
                      decoration: BoxDecoration(
                          color: AppColors.card,
                          borderRadius: BorderRadius.circular(18),
                          border: Border.all(
                              color: Colors.white.withOpacity(0.08))),
                      child: Row(
                        children: [
                          Icon(
                              vehicle.inspection.hasDamage
                                  ? Icons.info_outline
                                  : Icons.verified,
                              color: vehicle.inspection.hasDamage
                                  ? AppColors.gold
                                  : AppColors.green),
                          const SizedBox(width: 12),
                          Expanded(
                            child: Column(
                              crossAxisAlignment: CrossAxisAlignment.start,
                              children: [
                                Text(tr('VEHICLE CONDITION (EXPERTISE)'),
                                    style: const TextStyle(
                                        color: AppColors.muted,
                                        fontSize: 12,
                                        fontWeight: FontWeight.bold,
                                        letterSpacing: 1.1)),
                                const SizedBox(height: 4),
                                Text(
                                    vehicle.inspection.hasDamage
                                        ? tr('Details Available')
                                        : tr('No Damage'),
                                    style: const TextStyle(
                                        fontWeight: FontWeight.bold)),
                              ],
                            ),
                          ),
                          const Icon(Icons.chevron_right),
                        ],
                      ),
                    ),
                  ),
                  const SizedBox(height: 28),
                  Text(tr('Technical Specs'),
                      style: const TextStyle(
                          fontSize: 18, fontWeight: FontWeight.w900)),
                  const SizedBox(height: 14),
                  GridView.count(
                    crossAxisCount: 2,
                    shrinkWrap: true,
                    physics: const NeverScrollableScrollPhysics(),
                    crossAxisSpacing: 12,
                    mainAxisSpacing: 12,
                    childAspectRatio: 1.45,
                    children: _specCards(vehicle),
                  ),
                  const SizedBox(height: 28),
                  Text(tr('Description'),
                      style: const TextStyle(
                          fontSize: 18, fontWeight: FontWeight.w900)),
                  const SizedBox(height: 8),
                  Text(vehicle.description,
                      style:
                          const TextStyle(color: AppColors.muted, height: 1.5)),
                  const SizedBox(height: 20),
                  Builder(builder: (context) {
                    if (!widget.fromLocations) {
                      return Container(
                        padding: const EdgeInsets.all(16),
                        decoration: BoxDecoration(
                          color: AppColors.card,
                          borderRadius: BorderRadius.circular(16),
                          border: Border.all(
                              color: AppColors.gold.withOpacity(0.4)),
                        ),
                        child: Row(
                          children: [
                            const Icon(Icons.place_outlined,
                                color: AppColors.gold),
                            const SizedBox(width: 12),
                            Expanded(
                              child: Text(
                                tr('Go to Locations to reserve or pre-order this car.'),
                                style: const TextStyle(
                                    color: AppColors.muted, height: 1.4),
                              ),
                            ),
                          ],
                        ),
                      );
                    }
                    final isWarehouse = vehicle.locationId.trim().isEmpty;
                    return FilledButton.icon(
                      onPressed: () {
                        AppHaptics.medium();
                        Navigator.of(context).push(LuxuryPageRoute(
                            child: OrderScreen(
                                vehicle: vehicle, isPreOrder: isWarehouse)));
                      },
                      style: FilledButton.styleFrom(
                        backgroundColor: AppColors.gold,
                        foregroundColor: Colors.black,
                        minimumSize: const Size(double.infinity, 52),
                        shape: RoundedRectangleBorder(
                            borderRadius: BorderRadius.circular(18)),
                      ),
                      icon: Icon(isWarehouse
                          ? Icons.schedule
                          : Icons.shopping_bag_outlined),
                      label: Text(
                          isWarehouse
                              ? tr('Pre-order this car')
                              : tr('Reserve this car'),
                          style: const TextStyle(fontWeight: FontWeight.w900)),
                    );
                  }),
                  const SizedBox(height: 30),
                ],
              ),
            ),
          ),
        ],
      ),
    );
  }
}

class SpecCard extends StatelessWidget {
  final IconData icon;
  final String title;
  final String value;

  const SpecCard(
      {super.key, required this.icon, required this.title, required this.value});

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
          color: AppColors.card,
          borderRadius: BorderRadius.circular(18),
          border: Border.all(color: Colors.white.withOpacity(0.08))),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        mainAxisAlignment: MainAxisAlignment.center,
        children: [
          Icon(icon, color: AppColors.muted),
          const SizedBox(height: 10),
          Text(title, style: const TextStyle(color: AppColors.muted, fontSize: 12)),
          const SizedBox(height: 4),
          Text(value, style: const TextStyle(fontWeight: FontWeight.w900)),
        ],
      ),
    );
  }
}

// =============================================================================
// LOCATIONS
// =============================================================================

/// Detail-screen panel: where the car physically is + stock status.
class _LocationPanel extends StatelessWidget {
  final Vehicle vehicle;
  // null → show every location that has this model (Browse view).
  // a gallery id → show only that gallery. '' → show only the warehouse.
  final String? scopeLocationId;
  const _LocationPanel({required this.vehicle, this.scopeLocationId});

  @override
  Widget build(BuildContext context) {
    final all = VehicleService.instance.vehicles;
    final locations = VehicleService.instance.locations;

    int countAt(String locId) => all
        .where((v) =>
            v.brand == vehicle.brand &&
            v.model == vehicle.model &&
            v.locationId.trim() == locId)
        .length;

    final int warehouseTotal = all
        .where((v) =>
            v.brand == vehicle.brand &&
            v.model == vehicle.model &&
            v.locationId.trim().isEmpty)
        .length;

    List<MapEntry<GalleryLocation, int>> galleryLines;
    int warehouseCount;
    if (scopeLocationId == null) {
      galleryLines = locations
          .map((l) => MapEntry(l, countAt(l.id)))
          .where((e) => e.value > 0)
          .toList();
      warehouseCount = warehouseTotal;
    } else if (scopeLocationId!.trim().isEmpty) {
      galleryLines = [];
      warehouseCount = warehouseTotal;
    } else {
      galleryLines = locations
          .where((l) => l.id == scopeLocationId)
          .map((l) => MapEntry(l, countAt(l.id)))
          .where((e) => e.value > 0)
          .toList();
      warehouseCount = 0;
    }

    return Container(
      padding: const EdgeInsets.all(18),
      decoration: BoxDecoration(
          color: AppColors.card,
          borderRadius: BorderRadius.circular(18),
          border: Border.all(color: Colors.white.withOpacity(0.08))),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Text(tr('Where is this car?'),
                  style: const TextStyle(
                      color: AppColors.muted,
                      fontSize: 12,
                      fontWeight: FontWeight.bold,
                      letterSpacing: 1.1)),
              const Spacer(),
              AvailabilityBadge(vehicle: vehicle),
            ],
          ),
          const SizedBox(height: 4),
          Text('${vehicle.brand} ${vehicle.model}',
              style: const TextStyle(color: AppColors.muted, fontSize: 13)),
          const SizedBox(height: 14),
          if (galleryLines.isEmpty && warehouseCount == 0)
            Text(tr('Currently unavailable'),
                style: const TextStyle(color: AppColors.muted, fontSize: 13))
          else ...[
            ...galleryLines.map((e) => Padding(
                  padding: const EdgeInsets.only(bottom: 10),
                  child: Row(
                    children: [
                      const Icon(Icons.place, color: AppColors.gold, size: 20),
                      const SizedBox(width: 10),
                      Expanded(
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Text(e.key.name,
                                style: const TextStyle(
                                    fontWeight: FontWeight.w900)),
                            Text(e.key.city,
                                style: const TextStyle(
                                    color: AppColors.muted, fontSize: 13)),
                          ],
                        ),
                      ),
                      Text('${e.value} ${tr('available')}',
                          style: const TextStyle(
                              color: AppColors.green,
                              fontWeight: FontWeight.w900)),
                    ],
                  ),
                )),
            if (warehouseCount > 0)
              Row(
                children: [
                  const Icon(Icons.warehouse,
                      color: AppColors.muted, size: 20),
                  const SizedBox(width: 10),
                  Expanded(
                    child: Text(tr('Warehouse'),
                        style: const TextStyle(fontWeight: FontWeight.w900)),
                  ),
                  Text('$warehouseCount ${tr('for pre-order')}',
                      style: const TextStyle(
                          color: AppColors.gold, fontWeight: FontWeight.w900)),
                ],
              ),
          ],
        ],
      ),
    );
  }
}

/// Tappable list of gallery locations (+ warehouse). Each opens its filtered
/// inventory.
class LocationsScreen extends StatelessWidget {
  const LocationsScreen({super.key});

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
          backgroundColor: AppColors.background, title: Text(tr('Locations'))),
      body: ListenableBuilder(
        listenable: VehicleService.instance,
        builder: (context, _) {
          final svc = VehicleService.instance;
          if (svc.isLoading) return const LuxuryHomeSkeleton();
          final locs = svc.locations;
          final warehouseCount =
              svc.vehicles.where((v) => v.locationId.trim().isEmpty).length;

          void open(String galleryId) {
            AppHaptics.light();
            Navigator.of(context).push(LuxuryPageRoute(
                child: GalleryInventoryScreen(galleryId: galleryId)));
          }

          return ListView(
            padding: const EdgeInsets.all(16),
            children: [
              ...locs.map((loc) => _GalleryTile(
                    title: loc.name,
                    subtitle: '${loc.address} · ${loc.city}',
                    count: svc.vehiclesAtLocation(loc.id).length,
                    icon: Icons.storefront,
                    onTap: () => open(loc.id),
                  )),
              _GalleryTile(
                title: tr('Warehouse'),
                subtitle: tr('Pre-order stock'),
                count: warehouseCount,
                icon: Icons.warehouse,
                onTap: () => open(''),
              ),
            ],
          );
        },
      ),
    );
  }
}

class _GalleryTile extends StatelessWidget {
  final String title;
  final String subtitle;
  final int count;
  final IconData icon;
  final VoidCallback onTap;

  const _GalleryTile({
    required this.title,
    required this.subtitle,
    required this.count,
    required this.icon,
    required this.onTap,
  });

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 12),
      child: Material(
        color: AppColors.card,
        borderRadius: BorderRadius.circular(16),
        child: InkWell(
          onTap: onTap,
          borderRadius: BorderRadius.circular(16),
          child: Container(
            padding: const EdgeInsets.all(16),
            decoration: BoxDecoration(
              borderRadius: BorderRadius.circular(16),
              border: Border.all(color: Colors.white.withOpacity(0.08)),
            ),
            child: Row(
              children: [
                CircleAvatar(
                  radius: 22,
                  backgroundColor: AppColors.gold.withOpacity(0.15),
                  child: Icon(icon, color: AppColors.gold),
                ),
                const SizedBox(width: 14),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(title,
                          style: const TextStyle(
                              fontSize: 16, fontWeight: FontWeight.w900)),
                      const SizedBox(height: 2),
                      Text(subtitle,
                          maxLines: 1,
                          overflow: TextOverflow.ellipsis,
                          style: const TextStyle(
                              color: AppColors.muted, fontSize: 13)),
                    ],
                  ),
                ),
                const SizedBox(width: 10),
                Text('$count',
                    style: const TextStyle(
                        color: AppColors.gold,
                        fontSize: 20,
                        fontWeight: FontWeight.w900)),
                const SizedBox(width: 4),
                const Icon(Icons.chevron_right, color: AppColors.muted),
              ],
            ),
          ),
        ),
      ),
    );
  }
}

// =============================================================================
// INSPECTION
// =============================================================================

class InspectionScreen extends StatelessWidget {
  final Vehicle vehicle;
  const InspectionScreen({super.key, required this.vehicle});

  @override
  Widget build(BuildContext context) {
    final inspection = vehicle.inspection;
    return Scaffold(
      appBar: AppBar(
          backgroundColor: AppColors.background,
          title: Text(tr('Inspection Report'))),
      body: ListView(
        padding: const EdgeInsets.all(18),
        children: [
          Text(tr('Certified by Anıl Galeri Experts'),
              textAlign: TextAlign.center,
              style: const TextStyle(color: AppColors.muted)),
          const SizedBox(height: 24),
          Container(
            decoration: BoxDecoration(
                color: AppColors.card,
                borderRadius: BorderRadius.circular(18),
                border: Border.all(color: Colors.white.withOpacity(0.08))),
            child: Column(
              children: [
                _PartRow(label: tr('Hood'), status: inspection.hood),
                _PartRow(label: tr('Roof'), status: inspection.roof),
                _PartRow(
                    label: tr('Front bumper'),
                    status: inspection.frontBumper),
                _PartRow(
                    label: tr('Rear bumper'), status: inspection.rearBumper),
                _PartRow(
                    label: tr('Left front door'),
                    status: inspection.leftFrontDoor),
                _PartRow(
                    label: tr('Right front door'),
                    status: inspection.rightFrontDoor),
                _PartRow(
                    label: tr('Left rear door'),
                    status: inspection.leftRearDoor),
                _PartRow(
                    label: tr('Right rear door'),
                    status: inspection.rightRearDoor,
                    last: true),
              ],
            ),
          ),
          const SizedBox(height: 22),
          Row(
            mainAxisAlignment: MainAxisAlignment.center,
            children: [
              LegendDot(color: AppColors.green, label: tr('Original')),
              const SizedBox(width: 14),
              LegendDot(color: AppColors.gold, label: tr('Painted')),
              const SizedBox(width: 14),
              LegendDot(color: AppColors.red, label: tr('Replaced')),
            ],
          ),
        ],
      ),
    );
  }
}

class _PartRow extends StatelessWidget {
  final String label;
  final PartStatus status;
  final bool last;
  const _PartRow({required this.label, required this.status, this.last = false});

  Color get _color {
    switch (status) {
      case PartStatus.original:
        return AppColors.green;
      case PartStatus.painted:
        return AppColors.gold;
      case PartStatus.replaced:
        return AppColors.red;
    }
  }

  String get _text {
    switch (status) {
      case PartStatus.original:
        return tr('Original');
      case PartStatus.painted:
        return tr('Painted');
      case PartStatus.replaced:
        return tr('Replaced');
    }
  }

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 14),
      decoration: BoxDecoration(
        border: last
            ? null
            : const Border(
                bottom: BorderSide(color: Color(0x14FFFFFF))),
      ),
      child: Row(
        children: [
          Expanded(
            child: Text(label,
                style: const TextStyle(fontWeight: FontWeight.w600)),
          ),
          Container(
            padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 5),
            decoration: BoxDecoration(
              color: _color.withOpacity(0.16),
              borderRadius: BorderRadius.circular(8),
              border: Border.all(color: _color.withOpacity(0.5)),
            ),
            child: Text(_text,
                style: TextStyle(
                    color: _color,
                    fontSize: 12,
                    fontWeight: FontWeight.bold)),
          ),
        ],
      ),
    );
  }
}

class LegendDot extends StatelessWidget {
  final Color color;
  final String label;
  const LegendDot({super.key, required this.color, required this.label});

  @override
  Widget build(BuildContext context) {
    return Row(
      mainAxisSize: MainAxisSize.min,
      children: [
        CircleAvatar(radius: 6, backgroundColor: color),
        const SizedBox(width: 6),
        Text(label, style: const TextStyle(color: AppColors.muted, fontSize: 12)),
      ],
    );
  }
}

// =============================================================================
// SETTINGS
// =============================================================================

class SettingsScreen extends StatelessWidget {
  final AppUser user;
  const SettingsScreen({super.key, required this.user});

  @override
  Widget build(BuildContext context) {
    final settings = AppSettings.instance;
    return Scaffold(
      appBar: AppBar(
          backgroundColor: AppColors.background, title: Text(tr('Settings'))),
      body: ListView(
        padding: const EdgeInsets.all(18),
        children: [
          Container(
            padding: const EdgeInsets.all(18),
            decoration: BoxDecoration(
                color: AppColors.card, borderRadius: BorderRadius.circular(18)),
            child: Row(
              children: [
                const CircleAvatar(
                    radius: 26,
                    backgroundColor: AppColors.gold,
                    child: Icon(Icons.person, color: Colors.black)),
                const SizedBox(width: 14),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(user.fullName,
                          style:
                              const TextStyle(fontWeight: FontWeight.w900)),
                      Text(user.email,
                          style: const TextStyle(color: AppColors.muted)),
                    ],
                  ),
                ),
              ],
            ),
          ),
          const SizedBox(height: 36),
          OutlinedButton.icon(
            onPressed: () {
              AppHaptics.medium();
              Navigator.of(context).pushAndRemoveUntil(
                LuxuryPageRoute(child: const LoginScreen()),
                (route) => false,
              );
            },
            style: OutlinedButton.styleFrom(
              minimumSize: const Size(double.infinity, 52),
              side: const BorderSide(color: AppColors.red),
            ),
            icon: const Icon(Icons.logout, color: AppColors.red),
            label:
                Text(tr('Logout'), style: const TextStyle(color: AppColors.red)),
          ),
        ],
      ),
    );
  }
}

// =============================================================================
// ORDER (Reserve / Pre-order)
// =============================================================================

class OrderScreen extends StatefulWidget {
  final Vehicle vehicle;
  final bool isPreOrder;
  const OrderScreen(
      {super.key, required this.vehicle, required this.isPreOrder});

  @override
  State<OrderScreen> createState() => _OrderScreenState();
}

class _OrderScreenState extends State<OrderScreen> {
  final _formKey = GlobalKey<FormState>();
  final _name = TextEditingController();
  final _phone = TextEditingController();
  final _email = TextEditingController();
  final _note = TextEditingController();
  bool _submitting = false;

  bool get _isReserve => !widget.isPreOrder;

  // Reserve: you can collect from any gallery that actually stocks this model.
  // Pre-order: you can have it brought to any of the galleries.
  List<GalleryLocation> get _pickupGalleries {
    final locations = VehicleService.instance.locations;
    // Pre-order: deliver to any gallery. Reserve: only the gallery this car
    // is actually in (the one the user opened from Locations).
    if (widget.isPreOrder) return locations;
    final own = widget.vehicle.locationId.trim();
    final scoped = locations.where((l) => l.id == own).toList();
    return scoped.isEmpty ? locations : scoped;
  }

  late String _targetGallery = _initialGallery();

  String _initialGallery() {
    final galleries = _pickupGalleries;
    if (galleries.isEmpty) return '';
    // Prefer the car's own gallery if it's a valid pickup option.
    final own = widget.vehicle.locationId.trim();
    if (own.isNotEmpty && galleries.any((g) => g.id == own)) return own;
    return galleries.first.id;
  }

  @override
  void dispose() {
    for (final c in [_name, _phone, _email, _note]) {
      c.dispose();
    }
    super.dispose();
  }

  Future<void> _submit() async {
    if (!_formKey.currentState!.validate()) return;
    AppHaptics.medium();
    setState(() => _submitting = true);
    try {
      await VehicleService.instance.createOrder(
        vehicleId: widget.vehicle.id,
        customerName: _name.text.trim(),
        phone: _phone.text.trim(),
        email: _email.text.trim(),
        type: _isReserve ? 'RESERVE' : 'PREORDER',
        note: _note.text.trim(),
        targetLocationId: _targetGallery,
      );
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(
          content: Text(_isReserve
              ? tr('Reservation sent. The dealership will contact you.')
              : tr('Pre-order sent. The dealership will contact you.'))));
      Navigator.pop(context);
    } catch (e) {
      if (!mounted) return;
      setState(() => _submitting = false);
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(
          content: Text(
              tr('Could not send. Check your connection and try again.')),
          backgroundColor: AppColors.red));
    }
  }

  String? _required(String? v) =>
      (v == null || v.trim().isEmpty) ? tr('Required') : null;

  @override
  Widget build(BuildContext context) {
    final v = widget.vehicle;
    return Scaffold(
      appBar: AppBar(
          backgroundColor: AppColors.background,
          title: Text(
              _isReserve ? tr('Reserve this car') : tr('Pre-order this car'))),
      body: Form(
        key: _formKey,
        child: ListView(
          padding: const EdgeInsets.all(18),
          children: [
            Container(
              padding: const EdgeInsets.all(16),
              decoration: BoxDecoration(
                  color: AppColors.card,
                  borderRadius: BorderRadius.circular(16),
                  border: Border.all(color: Colors.white.withOpacity(0.08))),
              child: Row(
                children: [
                  Icon(
                      _isReserve
                          ? Icons.shopping_bag_outlined
                          : Icons.schedule,
                      color: AppColors.gold),
                  const SizedBox(width: 12),
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(v.fullName,
                            style:
                                const TextStyle(fontWeight: FontWeight.w900)),
                        Text(
                            _isReserve
                                ? tr('In stock - reserve now')
                                : tr('Not in stock - order for future delivery'),
                            style: const TextStyle(
                                color: AppColors.muted, fontSize: 12)),
                      ],
                    ),
                  ),
                  Text(v.formattedPrice,
                      style: const TextStyle(
                          color: AppColors.gold, fontWeight: FontWeight.w900)),
                ],
              ),
            ),
            const SizedBox(height: 18),
            Text(
                _isReserve
                    ? tr('Where would you like to pick it up?')
                    : tr('Which gallery should we bring it to?'),
                style: const TextStyle(fontWeight: FontWeight.w700)),
            const SizedBox(height: 8),
            Container(
              padding: const EdgeInsets.symmetric(horizontal: 14),
              decoration: BoxDecoration(
                  color: AppColors.card,
                  borderRadius: BorderRadius.circular(14)),
              child: DropdownButtonHideUnderline(
                child: DropdownButton<String>(
                  isExpanded: true,
                  value: _targetGallery.isEmpty ? null : _targetGallery,
                  dropdownColor: AppColors.card,
                  items: _pickupGalleries
                      .map((loc) => DropdownMenuItem(
                          value: loc.id, child: Text(loc.name)))
                      .toList(),
                  onChanged: (v) => setState(() => _targetGallery = v ?? ''),
                ),
              ),
            ),
            const SizedBox(height: 14),
            _field(_name, tr('Your name'), validator: _required),
            _field(_phone, tr('Phone'),
                keyboard: TextInputType.phone, validator: _required),
            _field(_email, tr('Email (optional)'),
                keyboard: TextInputType.emailAddress),
            _field(_note, tr('Notes (optional)'), maxLines: 3),
            const SizedBox(height: 24),
            FilledButton(
              onPressed: _submitting ? null : _submit,
              style: FilledButton.styleFrom(
                backgroundColor: AppColors.gold,
                foregroundColor: Colors.black,
                minimumSize: const Size(double.infinity, 54),
                shape: RoundedRectangleBorder(
                    borderRadius: BorderRadius.circular(16)),
              ),
              child: _submitting
                  ? const SizedBox(
                      height: 20,
                      width: 20,
                      child: CircularProgressIndicator(
                          strokeWidth: 2, color: Colors.black))
                  : Text(
                      _isReserve
                          ? tr('Confirm reservation')
                          : tr('Confirm pre-order'),
                      style: const TextStyle(fontWeight: FontWeight.w900)),
            ),
          ],
        ),
      ),
    );
  }

  Widget _field(TextEditingController c, String label,
      {TextInputType? keyboard,
      int maxLines = 1,
      String? Function(String?)? validator}) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 14),
      child: TextFormField(
        controller: c,
        keyboardType: keyboard,
        maxLines: maxLines,
        validator: validator,
        decoration: InputDecoration(
          labelText: label,
          filled: true,
          fillColor: AppColors.card,
          border: OutlineInputBorder(
              borderRadius: BorderRadius.circular(14),
              borderSide: BorderSide.none),
        ),
      ),
    );
  }
}

// =============================================================================
// ADMIN (CRUD)
// =============================================================================

class AdminScreen extends StatelessWidget {
  const AdminScreen({super.key});

  @override
  Widget build(BuildContext context) {
    final service = VehicleService.instance;
    return Scaffold(
      appBar: AppBar(
          backgroundColor: AppColors.background,
          title: Text(tr('Manage Vehicles'))),
      floatingActionButton: FloatingActionButton.extended(
        onPressed: () {
          AppHaptics.medium();
          Navigator.of(context)
              .push(LuxuryPageRoute(child: const VehicleFormScreen()));
        },
        backgroundColor: AppColors.gold,
        foregroundColor: Colors.black,
        icon: const Icon(Icons.add),
        label: Text(tr('Add Vehicle')),
      ),
      body: ListenableBuilder(
        listenable: service,
        builder: (context, _) {
          final vehicles = service.vehicles;
          return ListView.separated(
            padding: const EdgeInsets.all(18),
            itemCount: vehicles.length,
            separatorBuilder: (_, __) => const SizedBox(height: 10),
            itemBuilder: (context, index) {
              final vehicle = vehicles[index];
              return ListTile(
                tileColor: AppColors.card,
                shape: RoundedRectangleBorder(
                    borderRadius: BorderRadius.circular(16)),
                leading:
                    const Icon(Icons.directions_car, color: AppColors.gold),
                title: Text(vehicle.fullName),
                subtitle: Text(vehicle.formattedPrice),
                trailing: Wrap(
                  children: [
                    IconButton(
                      onPressed: () {
                        AppHaptics.light();
                        Navigator.of(context).push(LuxuryPageRoute(
                            child: VehicleFormScreen(existing: vehicle)));
                      },
                      icon: const Icon(Icons.edit),
                    ),
                    IconButton(
                      onPressed: () => _confirmDelete(context, vehicle),
                      icon: const Icon(Icons.delete_outline),
                    ),
                  ],
                ),
              );
            },
          );
        },
      ),
    );
  }

  void _confirmDelete(BuildContext context, Vehicle vehicle) {
    AppHaptics.medium();
    showDialog(
      context: context,
      builder: (ctx) => AlertDialog(
        backgroundColor: AppColors.card,
        title: Text(tr('Delete vehicle?')),
        content: Text('${vehicle.fullName}\n${tr('This action cannot be undone.')}'),
        actions: [
          TextButton(
              onPressed: () => Navigator.pop(ctx), child: Text(tr('Cancel'))),
          FilledButton(
            style: FilledButton.styleFrom(backgroundColor: AppColors.red),
            onPressed: () {
              VehicleService.instance.deleteVehicle(vehicle.id);
              Navigator.pop(ctx);
            },
            child: Text(tr('Delete')),
          ),
        ],
      ),
    );
  }
}

class VehicleFormScreen extends StatefulWidget {
  final Vehicle? existing;
  const VehicleFormScreen({super.key, this.existing});

  @override
  State<VehicleFormScreen> createState() => _VehicleFormScreenState();
}

class _VehicleFormScreenState extends State<VehicleFormScreen> {
  final _formKey = GlobalKey<FormState>();
  late final TextEditingController _brand;
  late final TextEditingController _model;
  late final TextEditingController _trim;
  late final TextEditingController _price;
  late final TextEditingController _year;
  late final TextEditingController _mileage;
  late final TextEditingController _power;
  late final TextEditingController _topSpeed;
  late final TextEditingController _color;
  late final TextEditingController _image;
  late final TextEditingController _description;

  FuelType _fuel = FuelType.petrol;
  Transmission _transmission = Transmission.automatic;
  BodyType _body = BodyType.sedan;
  bool _hotDeal = false;
  bool _loanEligible = true;
  bool _tradeIn = true;
  String _locationId =
      VehicleService.instance.locations.isNotEmpty
          ? VehicleService.instance.locations.first.id
          : '';
  bool _inStock = true;

  bool get _isEdit => widget.existing != null;

  @override
  void initState() {
    super.initState();
    final v = widget.existing;
    _brand = TextEditingController(text: v?.brand ?? '');
    _model = TextEditingController(text: v?.model ?? '');
    _trim = TextEditingController(text: v?.trimPackage ?? '');
    _price = TextEditingController(text: v?.price.toStringAsFixed(0) ?? '');
    _year = TextEditingController(text: v?.year.toString() ?? '2024');
    _mileage = TextEditingController(text: v?.mileage.toString() ?? '0');
    _power = TextEditingController(text: v?.specs.powerHp.toString() ?? '0');
    _topSpeed =
        TextEditingController(text: v?.specs.topSpeed.toString() ?? '0');
    _color = TextEditingController(text: v?.specs.color ?? '');
    _image = TextEditingController(
        text: v?.images.isNotEmpty == true ? v!.images.first.imageUrl : '');
    _description = TextEditingController(text: v?.description ?? '');
    if (v != null) {
      _fuel = v.fuelType;
      _transmission = v.transmission;
      _body = v.bodyType;
      _hotDeal = v.isHotDeal;
      _loanEligible = v.isLoanEligible;
      _tradeIn = v.acceptsTradeIn;
      if (v.locationId.isNotEmpty) _locationId = v.locationId;
      _inStock = v.inStock;
    }
  }

  @override
  void dispose() {
    for (final c in [
      _brand,
      _model,
      _trim,
      _price,
      _year,
      _mileage,
      _power,
      _topSpeed,
      _color,
      _image,
      _description
    ]) {
      c.dispose();
    }
    super.dispose();
  }

  void _save() {
    if (!_formKey.currentState!.validate()) return;
    AppHaptics.medium();
    final id = widget.existing?.id ?? VehicleService.instance.nextVehicleId();
    final price = double.tryParse(_price.text) ?? 0;
    final imageUrl = _image.text.trim();

    final vehicle = Vehicle(
      id: id,
      brand: _brand.text.trim(),
      model: _model.text.trim(),
      trimPackage: _trim.text.trim(),
      price: price,
      currency: r'$',
      year: int.tryParse(_year.text) ?? DateTime.now().year,
      mileage: int.tryParse(_mileage.text) ?? 0,
      fuelType: _fuel,
      transmission: _transmission,
      bodyType: _body,
      isHotDeal: _hotDeal,
      isLoanEligible: _loanEligible,
      acceptsTradeIn: _tradeIn,
      description: _description.text.trim(),
      specs: VehicleSpecs(
        vehicleId: id,
        powerHp: int.tryParse(_power.text) ?? 0,
        topSpeed: int.tryParse(_topSpeed.text) ?? 0,
        zeroToHundred: widget.existing?.specs.zeroToHundred ?? 0,
        engineCc: widget.existing?.specs.engineCc ?? 0,
        torque: widget.existing?.specs.torque ?? 0,
        batteryKwh: widget.existing?.specs.batteryKwh ?? 0,
        rangeKm: widget.existing?.specs.rangeKm ?? 0,
        color: _color.text.trim(),
        drivetrain: widget.existing?.specs.drivetrain ?? 'AWD',
      ),
      inspection: widget.existing?.inspection ??
          VehicleInspection(
            vehicleId: id,
            hood: PartStatus.original,
            roof: PartStatus.original,
            frontBumper: PartStatus.original,
            rearBumper: PartStatus.original,
            leftFrontDoor: PartStatus.original,
            rightFrontDoor: PartStatus.original,
            leftRearDoor: PartStatus.original,
            rightRearDoor: PartStatus.original,
            tramerAmount: 0,
          ),
      images: imageUrl.isEmpty
          ? (widget.existing?.images ?? const [])
          : [
              VehicleImage(
                  id: '$id-img',
                  vehicleId: id,
                  imageUrl: imageUrl,
                  isCover: true,
                  sortOrder: 1),
            ],
      damageHistory: widget.existing?.damageHistory ?? const [],
      locationId: _locationId,
      inStock: _inStock,
    );

    if (_isEdit) {
      VehicleService.instance.updateVehicle(vehicle);
    } else {
      VehicleService.instance.addVehicle(vehicle);
    }
    Navigator.pop(context);
  }

  String? _required(String? v) =>
      (v == null || v.trim().isEmpty) ? tr('Required') : null;

  String? _numeric(String? v) {
    if (v == null || v.trim().isEmpty) return tr('Required');
    if (double.tryParse(v.trim()) == null) return tr('Enter a valid number');
    return null;
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
          backgroundColor: AppColors.background,
          title: Text(_isEdit ? tr('Edit Vehicle') : tr('Add Vehicle'))),
      body: Form(
        key: _formKey,
        child: ListView(
          padding: const EdgeInsets.all(18),
          children: [
            _field(_brand, tr('Brand'), validator: _required),
            _field(_model, tr('Model'), validator: _required),
            _field(_trim, tr('Trim / Package')),
            _field(_price, tr('Price (USD)'),
                keyboard: TextInputType.number, validator: _numeric),
            _field(_year, tr('Year'),
                keyboard: TextInputType.number, validator: _numeric),
            _field(_mileage, tr('Mileage'),
                keyboard: TextInputType.number, validator: _numeric),
            _field(_power, tr('Power'), keyboard: TextInputType.number),
            _field(_topSpeed, tr('Top Speed'),
                keyboard: TextInputType.number),
            _field(_color, tr('Color')),
            _field(_image, tr('Image URL')),
            _field(_description, tr('Description'), maxLines: 3),
            const SizedBox(height: 6),
            FilterLabelDark(tr('Fuel').toUpperCase()),
            const SizedBox(height: 8),
            _enumChips<FuelType>(FuelType.values, _fuel, (e) => e.localizedLabel,
                (e) => setState(() => _fuel = e)),
            const SizedBox(height: 14),
            FilterLabelDark(tr('Transmission').toUpperCase()),
            const SizedBox(height: 8),
            _enumChips<Transmission>(Transmission.values, _transmission,
                (e) => e.localizedLabel, (e) => setState(() => _transmission = e)),
            const SizedBox(height: 14),
            FilterLabelDark(tr('Body').toUpperCase()),
            const SizedBox(height: 8),
            _enumChips<BodyType>(BodyType.values, _body, (e) => e.localizedLabel,
                (e) => setState(() => _body = e)),
            const SizedBox(height: 14),
            FilterLabelDark(tr('Location').toUpperCase()),
            const SizedBox(height: 8),
            Wrap(
              spacing: 8,
              runSpacing: 8,
              children: VehicleService.instance.locations.map((loc) {
                final selected = _locationId == loc.id;
                return ChoiceChip(
                  selected: selected,
                  backgroundColor: AppColors.cardLight,
                  selectedColor: AppColors.gold,
                  label: Text(loc.city,
                      style: TextStyle(
                          color: selected ? Colors.black : Colors.white,
                          fontWeight: FontWeight.w600)),
                  onSelected: (_) {
                    AppHaptics.light();
                    setState(() => _locationId = loc.id);
                  },
                );
              }).toList(),
            ),
            const SizedBox(height: 8),
            SwitchListTile(
              value: _hotDeal,
              activeColor: AppColors.gold,
              title: Text(tr('Hot deal')),
              onChanged: (v) => setState(() => _hotDeal = v),
            ),
            SwitchListTile(
              value: _loanEligible,
              activeColor: AppColors.gold,
              title: Text(tr('Loan eligible')),
              onChanged: (v) => setState(() => _loanEligible = v),
            ),
            SwitchListTile(
              value: _tradeIn,
              activeColor: AppColors.gold,
              title: Text(tr('Accepts trade-in')),
              onChanged: (v) => setState(() => _tradeIn = v),
            ),
            const SizedBox(height: 20),
            FilledButton(
              onPressed: _save,
              style: FilledButton.styleFrom(
                backgroundColor: AppColors.gold,
                foregroundColor: Colors.black,
                minimumSize: const Size(double.infinity, 54),
                shape: RoundedRectangleBorder(
                    borderRadius: BorderRadius.circular(16)),
              ),
              child: Text(tr('Save'),
                  style: const TextStyle(fontWeight: FontWeight.w900)),
            ),
          ],
        ),
      ),
    );
  }

  Widget _enumChips<T>(List<T> values, T selectedValue,
      String Function(T) label, void Function(T) onSelect) {
    return Wrap(
      spacing: 8,
      runSpacing: 8,
      children: values.map((e) {
        final selected = e == selectedValue;
        return ChoiceChip(
          selected: selected,
          backgroundColor: AppColors.cardLight,
          selectedColor: AppColors.gold,
          label: Text(label(e),
              style: TextStyle(
                  color: selected ? Colors.black : Colors.white,
                  fontWeight: FontWeight.w600)),
          onSelected: (_) {
            AppHaptics.light();
            onSelect(e);
          },
        );
      }).toList(),
    );
  }

  Widget _field(TextEditingController c, String label,
      {TextInputType? keyboard,
      int maxLines = 1,
      String? Function(String?)? validator}) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 14),
      child: TextFormField(
        controller: c,
        keyboardType: keyboard,
        maxLines: maxLines,
        validator: validator,
        decoration: InputDecoration(
          labelText: label,
          filled: true,
          fillColor: AppColors.card,
          border: OutlineInputBorder(
              borderRadius: BorderRadius.circular(14),
              borderSide: BorderSide.none),
        ),
      ),
    );
  }
}
