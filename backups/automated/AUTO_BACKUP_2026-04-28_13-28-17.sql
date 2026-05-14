-- MariaDB dump 10.19  Distrib 10.4.32-MariaDB, for Win64 (AMD64)
--
-- Host: localhost    Database: property_system
-- ------------------------------------------------------
-- Server version	10.4.32-MariaDB

/*!40101 SET @OLD_CHARACTER_SET_CLIENT=@@CHARACTER_SET_CLIENT */;
/*!40101 SET @OLD_CHARACTER_SET_RESULTS=@@CHARACTER_SET_RESULTS */;
/*!40101 SET @OLD_COLLATION_CONNECTION=@@COLLATION_CONNECTION */;
/*!40101 SET NAMES utf8mb4 */;
/*!40103 SET @OLD_TIME_ZONE=@@TIME_ZONE */;
/*!40103 SET TIME_ZONE='+00:00' */;
/*!40014 SET @OLD_UNIQUE_CHECKS=@@UNIQUE_CHECKS, UNIQUE_CHECKS=0 */;
/*!40014 SET @OLD_FOREIGN_KEY_CHECKS=@@FOREIGN_KEY_CHECKS, FOREIGN_KEY_CHECKS=0 */;
/*!40101 SET @OLD_SQL_MODE=@@SQL_MODE, SQL_MODE='NO_AUTO_VALUE_ON_ZERO' */;
/*!40111 SET @OLD_SQL_NOTES=@@SQL_NOTES, SQL_NOTES=0 */;

--
-- Table structure for table `audit_logs`
--

DROP TABLE IF EXISTS `audit_logs`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `audit_logs` (
  `id` int(11) NOT NULL AUTO_INCREMENT,
  `username` varchar(255) NOT NULL,
  `action` text NOT NULL,
  `timestamp` datetime NOT NULL,
  PRIMARY KEY (`id`),
  KEY `idx_audit_logs_timestamp` (`timestamp`),
  KEY `idx_audit_logs_username` (`username`(100))
) ENGINE=InnoDB AUTO_INCREMENT=215 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `audit_logs`
--

LOCK TABLES `audit_logs` WRITE;
/*!40000 ALTER TABLE `audit_logs` DISABLE KEYS */;
INSERT INTO `audit_logs` VALUES (1,'admin','User login successful','2026-04-21 15:43:54'),(2,'admin','Created user account Kevin','2026-04-21 15:45:31'),(3,'admin','User logged out','2026-04-21 15:45:36'),(4,'Kevin','User login successful','2026-04-21 15:45:42'),(5,'Kevin','User logged out','2026-04-21 15:46:08'),(6,'Kevin','User login successful','2026-04-21 15:50:07'),(7,'Kevin','User logged out','2026-04-21 15:50:55'),(8,'Kevin','User login successful','2026-04-21 15:52:50'),(9,'Kevin','User logged out','2026-04-21 15:59:35'),(10,'Kevin','User login successful','2026-04-21 15:59:43'),(11,'Kevin','User logged out','2026-04-21 16:00:38'),(12,'Kevin','User login successful','2026-04-21 16:02:55'),(13,'Kevin','User logged out','2026-04-21 16:04:07'),(14,'Kevin','User login successful','2026-04-21 16:20:09'),(15,'Kevin','User logged out','2026-04-21 16:20:53'),(16,'Kevin','User login successful','2026-04-21 16:22:35'),(17,'Kevin','Created property record TD 06-0001-0001 with payment','2026-04-21 16:23:01'),(18,'Kevin','Disabled user account ID 1','2026-04-21 16:23:27'),(19,'Kevin','Disabled user account ID 2','2026-04-21 16:23:31'),(20,'Kevin','User logged out','2026-04-21 16:24:47'),(21,'Kevin','User login successful','2026-04-21 16:25:09'),(22,'Kevin','Created user account leo','2026-04-21 16:25:50'),(23,'Kevin','User logged out','2026-04-21 16:25:55'),(24,'leo','User login successful','2026-04-21 16:26:01'),(25,'leo','User logged out','2026-04-21 16:26:08'),(26,'Kevin','User login successful','2026-04-21 16:27:06'),(27,'Kevin','User logged out','2026-04-21 16:28:44'),(28,'Kevin','User login successful','2026-04-21 16:34:06'),(29,'Kevin','User logged out','2026-04-21 16:34:12'),(30,'leo','User login successful','2026-04-21 16:34:17'),(31,'leo','Updated user account leo','2026-04-21 16:34:50'),(32,'leo','Updated user account leo','2026-04-21 16:35:02'),(33,'leo','User logged out','2026-04-21 16:35:13'),(34,'Kevin','User login successful','2026-04-21 16:36:52'),(35,'Kevin','Updated user account leo','2026-04-21 16:36:59'),(36,'Kevin','Updated user account leo','2026-04-21 16:37:10'),(37,'Kevin','User logged out','2026-04-21 16:37:12'),(38,'leo','User login successful','2026-04-21 16:37:17'),(39,'leo','User logged out','2026-04-21 16:37:26'),(40,'Kevin','User login successful','2026-04-21 16:37:39'),(41,'Kevin','User logged out','2026-04-21 16:40:58'),(42,'Kevin','User login successful','2026-04-21 16:45:57'),(43,'Kevin','User logged out','2026-04-21 16:47:11'),(44,'Kevin','User login successful','2026-04-21 16:47:18'),(45,'Kevin','Generated receipt OR 8080 for TD 06-0001-0001','2026-04-21 16:47:32'),(46,'Kevin','User logged out','2026-04-21 16:49:34'),(47,'Kevin','User login successful','2026-04-21 17:02:59'),(48,'Kevin','Created property record TD 06-0001-0001 with payment','2026-04-21 17:05:35'),(49,'Kevin','Created property record TD 06-0001-0001 with payment','2026-04-21 17:06:19'),(50,'Kevin','Moved property record to recycle bin: 06-0001-0001','2026-04-21 17:09:56'),(51,'Kevin','User logged out','2026-04-21 17:11:05'),(52,'Kevin','User login successful','2026-04-21 17:11:15'),(53,'Kevin','Updated user account kevin','2026-04-21 17:13:11'),(54,'Kevin','User logged out','2026-04-21 17:14:21'),(55,'kevin','User login successful','2026-04-21 17:49:09'),(56,'kevin','User logged out','2026-04-21 17:49:59'),(57,'kevin','User login successful','2026-04-22 08:38:53'),(58,'kevin','User logged out','2026-04-22 08:38:58'),(59,'kevin','User login successful','2026-04-22 08:39:58'),(60,'kevin','Created property record TD 06-0001-0001 with payment','2026-04-22 08:41:02'),(61,'kevin','Created property record TD 06-0001-0002 with payment','2026-04-22 08:41:57'),(62,'kevin','Generated receipt OR 5555 for TD 06-0001-0002','2026-04-22 08:43:07'),(63,'kevin','User logged out','2026-04-22 08:48:43'),(64,'kevin','User login successful','2026-04-22 10:41:36'),(65,'kevin','User logged out','2026-04-22 10:41:54'),(66,'kevin','User login successful','2026-04-22 10:43:03'),(67,'kevin','User logged out','2026-04-22 10:44:00'),(68,'kevin','User login successful','2026-04-22 10:46:08'),(69,'kevin','User logged out','2026-04-22 10:46:18'),(70,'leo','User login successful','2026-04-22 10:46:24'),(71,'leo','User logged out','2026-04-22 10:48:59'),(72,'kevin','User login successful','2026-04-22 10:57:29'),(73,'kevin','User login successful','2026-04-22 11:40:26'),(74,'kevin','User logged out','2026-04-22 11:40:29'),(75,'kevin','User login successful','2026-04-22 11:44:24'),(76,'kevin','User logged out','2026-04-22 11:44:26'),(77,'kevin','User login successful','2026-04-22 14:15:18'),(78,'kevin','User login successful','2026-04-22 14:29:07'),(79,'kevin','User logged out','2026-04-22 14:29:12'),(80,'kevin','User login successful','2026-04-22 14:35:45'),(81,'kevin','Updated user account leo','2026-04-22 14:35:52'),(82,'kevin','Created user account raquel','2026-04-22 14:36:36'),(83,'kevin','Updated user account leo','2026-04-22 14:36:42'),(84,'kevin','User logged out','2026-04-22 14:36:47'),(85,'leo','User login successful','2026-04-22 14:36:53'),(86,'leo','User logged out','2026-04-22 14:37:08'),(87,'kevin','User login successful','2026-04-22 14:41:24'),(88,'kevin','User login successful','2026-04-22 14:42:04'),(89,'kevin','Created property record TD 06-0017-00112 with payment','2026-04-22 14:46:59'),(90,'kevin','Generated receipt OR 4594849 for TD 06-0017-00112','2026-04-22 14:47:42'),(91,'kevin','Updated property record TD 06-0017-00112 with payment','2026-04-22 14:50:23'),(92,'kevin','Updated user account raquel','2026-04-22 14:52:05'),(93,'kevin','Restored property: kevin','2026-04-22 14:53:16'),(94,'kevin','User logged out','2026-04-22 14:56:07'),(95,'leo','User login successful','2026-04-22 14:58:08'),(96,'kevin','Imported Excel data: 29 inserted, 31 updated, 0 skipped, 0 failed','2026-04-22 14:58:25'),(97,'leo','Created property record TD 06-0001-0002 with payment','2026-04-22 15:01:12'),(98,'leo','Updated property record TD 06-0001-0002 with payment','2026-04-22 15:02:07'),(99,'leo','User logged out','2026-04-22 15:10:59'),(100,'kevin','User login successful','2026-04-22 15:12:16'),(101,'kevin','Imported Excel data: 2 inserted, 0 updated, 4 skipped, 0 failed','2026-04-22 15:12:40'),(102,'kevin','Imported Excel data: 0 inserted, 2 updated, 4 skipped, 0 failed','2026-04-22 15:12:57'),(103,'kevin','Imported Excel data: 0 inserted, 2 updated, 4 skipped, 0 failed','2026-04-22 15:13:22'),(104,'kevin','Imported Excel data: 1 inserted, 2 updated, 3 skipped, 0 failed','2026-04-22 15:14:11'),(105,'kevin','User logged out','2026-04-22 15:15:28'),(106,'kevin','User login successful','2026-04-22 15:15:40'),(107,'kevin','Imported Excel data: 0 inserted, 3 updated, 3 skipped, 0 failed','2026-04-22 15:15:44'),(108,'kevin','Imported Excel data: 0 inserted, 3 updated, 3 skipped, 0 failed','2026-04-22 15:15:54'),(109,'kevin','User logged out','2026-04-22 15:18:14'),(110,'kevin','User login successful','2026-04-22 15:18:21'),(111,'kevin','User logged out','2026-04-22 15:20:23'),(112,'kevin','User login successful','2026-04-22 15:20:32'),(113,'kevin','User logged out','2026-04-22 15:22:49'),(114,'kevin','User login successful','2026-04-22 15:22:55'),(115,'kevin','User logged out','2026-04-22 15:24:43'),(116,'kevin','User login successful','2026-04-22 15:24:50'),(117,'kevin','User logged out','2026-04-22 15:27:33'),(118,'kevin','User login successful','2026-04-22 15:27:42'),(119,'kevin','Imported Excel data: 1 inserted, 0 updated, 0 duplicates, 5 skipped, 0 failed','2026-04-22 15:27:45'),(120,'kevin','User logged out','2026-04-22 15:29:34'),(121,'kevin','User login successful','2026-04-22 15:29:41'),(122,'kevin','User logged out','2026-04-22 15:32:16'),(123,'kevin','User login successful','2026-04-22 15:39:56'),(124,'kevin','User logged out','2026-04-22 15:41:58'),(125,'kevin','User login successful','2026-04-22 15:51:02'),(126,'kevin','Updated property record TD 06-0001-0005 with payment','2026-04-22 15:51:29'),(127,'kevin','Generated receipt OR 5050 for TD 06-0001-0005','2026-04-22 15:51:38'),(128,'kevin','Updated property record TD 06-0001-0005 with payment','2026-04-22 15:52:16'),(129,'kevin','Generated receipt OR 5050 for TD 06-0001-0005','2026-04-22 15:52:30'),(130,'kevin','User logged out','2026-04-22 15:54:24'),(131,'leo','User login successful','2026-04-22 15:55:52'),(132,'leo','User logged out','2026-04-22 15:56:06'),(133,'kevin','User login successful','2026-04-22 15:56:13'),(134,'kevin','Updated user account leo','2026-04-22 15:56:26'),(135,'kevin','User logged out','2026-04-22 16:05:09'),(136,'kevin','User login successful','2026-04-22 16:05:15'),(137,'kevin','Moved property record to recycle bin: 06-0001-0001','2026-04-22 16:06:01'),(138,'kevin','Updated property record TD 06-0001-0001 with payment','2026-04-22 16:06:13'),(139,'kevin','User logged out','2026-04-22 16:16:59'),(140,'kevin','User login successful','2026-04-22 16:17:06'),(141,'kevin','Updated property record TD 06-0001-0001 with payment','2026-04-22 16:17:25'),(142,'kevin','User logged out','2026-04-22 16:17:30'),(143,'kevin','User login successful','2026-04-22 16:26:03'),(144,'kevin','Moved property record to recycle bin: 06-0001-0009','2026-04-22 16:27:35'),(145,'kevin','User logged out','2026-04-22 16:28:42'),(146,'kevin','User login successful','2026-04-22 16:30:22'),(147,'kevin','User logged out','2026-04-22 16:30:45'),(148,'kevin','User login successful','2026-04-22 16:43:53'),(149,'kevin','Generated statement of account for TD 06-0017-00112','2026-04-22 16:44:19'),(150,'kevin','Generated statement of account for TD 06-0001-0002','2026-04-22 16:46:06'),(151,'kevin','User logged out','2026-04-22 16:48:12'),(152,'kevin','User login successful','2026-04-22 16:49:20'),(153,'kevin','Generated statement of account for TD 06-0001-0002','2026-04-22 16:49:30'),(154,'kevin','Generated statement of account for TD 06-0001-0001','2026-04-22 16:49:54'),(155,'kevin','User logged out','2026-04-22 16:51:20'),(156,'kevin','User login successful','2026-04-22 16:51:38'),(157,'kevin','Generated statement of account for TD 06-0001-0005','2026-04-22 16:51:47'),(158,'kevin','User logged out','2026-04-22 16:54:02'),(159,'kevin','User login successful','2026-04-22 16:55:33'),(160,'kevin','User logged out','2026-04-22 16:55:57'),(161,'kevin','User login successful','2026-04-22 17:07:00'),(162,'kevin','User logged out','2026-04-22 17:07:29'),(163,'kevin','User login successful','2026-04-22 17:27:03'),(164,'kevin','Generated statement of account for TD 06-0017-00112','2026-04-22 17:29:22'),(165,'kevin','Updated property record TD 06-0001-0008 with payment','2026-04-22 17:31:47'),(166,'kevin','User logged out','2026-04-22 17:32:56'),(167,'kevin','User login successful','2026-04-23 09:52:13'),(168,'kevin','User logged out','2026-04-23 09:52:27'),(169,'kevin','User login successful','2026-04-23 10:00:29'),(170,'kevin','User logged out','2026-04-23 10:01:32'),(171,'kevin','User login successful','2026-04-23 10:57:42'),(172,'kevin','User logged out','2026-04-23 10:57:49'),(173,'kevin','User login successful','2026-04-23 11:03:35'),(174,'kevin','Generated statement of account for TD 06-0001-0002','2026-04-23 11:04:16'),(175,'kevin','Generated statement of account for TD 06-0001-0008','2026-04-23 11:04:27'),(176,'kevin','User logged out','2026-04-23 11:05:27'),(177,'kevin','User login successful','2026-04-23 11:41:47'),(178,'kevin','User login successful','2026-04-23 11:51:29'),(179,'kevin','User login successful','2026-04-23 12:55:28'),(180,'kevin','User logged out','2026-04-23 12:55:34'),(181,'kevin','User login successful','2026-04-23 13:02:05'),(182,'kevin','User logged out','2026-04-23 13:02:22'),(183,'kevin','User login successful','2026-04-27 13:34:13'),(184,'kevin','User login successful','2026-04-27 15:25:01'),(185,'kevin','Generated Notice of Delinquency for TD 06-0001-0002','2026-04-27 15:27:45'),(186,'kevin','User login successful','2026-04-27 15:29:21'),(187,'kevin','Created property record TD 06-0001-0006 with payment','2026-04-27 15:30:01'),(188,'kevin','Generated Notice of Delinquency for TD TD-2026-002','2026-04-27 15:31:09'),(189,'kevin','Created property record TD 06-0001-0002 with payment','2026-04-27 15:32:31'),(190,'kevin','User login successful','2026-04-27 15:50:05'),(191,'kevin','Created property record TD 06-0001-0005 with payment','2026-04-27 15:50:54'),(192,'kevin','User login successful','2026-04-27 16:50:34'),(193,'kevin','User login successful','2026-04-27 16:53:34'),(194,'kevin','User logged out','2026-04-27 16:55:02'),(195,'kevin','User login successful','2026-04-27 17:18:49'),(196,'kevin','User logged out','2026-04-27 17:19:15'),(197,'kevin','User login successful','2026-04-27 17:51:04'),(198,'kevin','User login successful','2026-04-28 09:32:01'),(199,'kevin','User login successful','2026-04-28 09:36:26'),(200,'kevin','User logged out','2026-04-28 09:36:33'),(201,'kevin','User login successful','2026-04-28 09:43:09'),(202,'kevin','User login successful','2026-04-28 10:11:36'),(203,'kevin','User login successful','2026-04-28 10:50:50'),(204,'kevin','Reset password for user account kevin','2026-04-28 10:51:59'),(205,'kevin','User logged out','2026-04-28 10:52:02'),(206,'kevin','User login successful','2026-04-28 10:52:08'),(207,'kevin','User logged out','2026-04-28 10:52:10'),(208,'kevin','User login successful','2026-04-28 10:56:00'),(209,'kevin','User logged out','2026-04-28 10:56:03'),(210,'kevin','User login successful','2026-04-28 11:33:21'),(211,'kevin','User logged out','2026-04-28 11:33:32'),(212,'kevin','User login successful','2026-04-28 11:33:59'),(213,'kevin','Updated property record TD 06-0001-0001 with payment','2026-04-28 11:36:28'),(214,'kevin','User logged out','2026-04-28 11:37:30');
/*!40000 ALTER TABLE `audit_logs` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `payment_billings`
--

DROP TABLE IF EXISTS `payment_billings`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `payment_billings` (
  `id` int(11) NOT NULL AUTO_INCREMENT,
  `payment_id` int(11) NOT NULL,
  `billing_id` int(11) NOT NULL,
  `tax_year` varchar(20) NOT NULL,
  `amount_paid` decimal(12,2) NOT NULL DEFAULT 0.00,
  `created_at` timestamp NOT NULL DEFAULT current_timestamp(),
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_payment_billings_payment_billing` (`payment_id`,`billing_id`),
  KEY `idx_payment_billings_payment_id` (`payment_id`),
  KEY `idx_payment_billings_billing_id` (`billing_id`),
  CONSTRAINT `fk_payment_billings_billing` FOREIGN KEY (`billing_id`) REFERENCES `property_billings` (`id`) ON DELETE CASCADE ON UPDATE CASCADE,
  CONSTRAINT `fk_payment_billings_payment` FOREIGN KEY (`payment_id`) REFERENCES `payments` (`id`) ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE=InnoDB AUTO_INCREMENT=24 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `payment_billings`
--

LOCK TABLES `payment_billings` WRITE;
/*!40000 ALTER TABLE `payment_billings` DISABLE KEYS */;
INSERT INTO `payment_billings` VALUES (2,9,9,'2026',1760.00,'2026-04-21 09:05:34'),(3,10,10,'2026',1760.00,'2026-04-21 09:06:18'),(5,12,13,'2026',40000.00,'2026-04-22 00:41:56'),(6,13,14,'2026',1000.00,'2026-04-22 06:46:50'),(7,14,15,'2024',1000.00,'2026-04-22 06:50:14'),(8,44,78,'2026',1700.00,'2026-04-22 07:01:10'),(9,45,79,'2024',40000.00,'2026-04-22 07:02:06'),(10,49,97,'2026',2100.00,'2026-04-22 07:27:45'),(12,11,12,'2026',1760.00,'2026-04-22 07:52:16'),(15,8,8,'2026',16160.00,'2026-04-22 08:17:24'),(16,51,104,'2024',699.99,'2026-04-22 09:31:42'),(17,51,105,'2025',700.00,'2026-04-22 09:31:42'),(18,51,97,'2026',700.00,'2026-04-22 09:31:42'),(19,52,107,'2020',10100.00,'2026-04-27 07:30:00'),(20,53,108,'2022',1700.00,'2026-04-27 07:32:30'),(21,54,109,'2026',1616.00,'2026-04-27 07:50:53'),(22,50,101,'2024',1100.00,'2026-04-28 03:36:26'),(23,50,102,'2025',660.00,'2026-04-28 03:36:26');
/*!40000 ALTER TABLE `payment_billings` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `payment_billings_legacy_20260421_1705`
--

DROP TABLE IF EXISTS `payment_billings_legacy_20260421_1705`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `payment_billings_legacy_20260421_1705` (
  `billing_id` int(11) NOT NULL AUTO_INCREMENT,
  `property_id` int(11) DEFAULT NULL,
  `tenant_id` int(11) DEFAULT NULL,
  `amount` decimal(10,2) DEFAULT NULL,
  `billing_date` date DEFAULT NULL,
  `due_date` date DEFAULT NULL,
  `status` varchar(50) DEFAULT NULL,
  `created_at` timestamp NOT NULL DEFAULT current_timestamp(),
  `payment_id` int(11) DEFAULT NULL,
  `tax_year` year(4) DEFAULT NULL,
  PRIMARY KEY (`billing_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `payment_billings_legacy_20260421_1705`
--

LOCK TABLES `payment_billings_legacy_20260421_1705` WRITE;
/*!40000 ALTER TABLE `payment_billings_legacy_20260421_1705` DISABLE KEYS */;
/*!40000 ALTER TABLE `payment_billings_legacy_20260421_1705` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `payment_post_locks`
--

DROP TABLE IF EXISTS `payment_post_locks`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `payment_post_locks` (
  `property_id` int(11) NOT NULL,
  `locked_by` varchar(255) NOT NULL,
  `locked_at` datetime NOT NULL,
  PRIMARY KEY (`property_id`),
  KEY `idx_payment_post_locks_locked_at` (`locked_at`),
  CONSTRAINT `fk_payment_post_locks_property` FOREIGN KEY (`property_id`) REFERENCES `properties` (`id`) ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `payment_post_locks`
--

LOCK TABLES `payment_post_locks` WRITE;
/*!40000 ALTER TABLE `payment_post_locks` DISABLE KEYS */;
/*!40000 ALTER TABLE `payment_post_locks` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `payments`
--

DROP TABLE IF EXISTS `payments`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `payments` (
  `id` int(11) NOT NULL AUTO_INCREMENT,
  `property_id` int(11) NOT NULL,
  `amount` decimal(12,2) NOT NULL DEFAULT 0.00,
  `or_number` varchar(255) DEFAULT NULL,
  `date_paid` date DEFAULT NULL,
  `tax_year` varchar(20) DEFAULT NULL,
  `posted_by` varchar(255) DEFAULT NULL,
  `payor_name` varchar(255) DEFAULT NULL,
  `is_archived` tinyint(1) NOT NULL DEFAULT 0,
  `created_at` timestamp NOT NULL DEFAULT current_timestamp(),
  PRIMARY KEY (`id`),
  KEY `idx_payments_property_id` (`property_id`),
  KEY `idx_payments_is_archived` (`is_archived`),
  CONSTRAINT `fk_payments_property` FOREIGN KEY (`property_id`) REFERENCES `properties` (`id`) ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE=InnoDB AUTO_INCREMENT=55 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `payments`
--

LOCK TABLES `payments` WRITE;
/*!40000 ALTER TABLE `payments` DISABLE KEYS */;
INSERT INTO `payments` VALUES (8,9,16160.00,'8080','2026-02-08','2026','JSJS','kevin 67',0,'2026-04-21 08:22:58'),(9,10,1760.00,'120120','2026-02-02','2026','SMV',NULL,0,'2026-04-21 09:05:34'),(10,11,1760.00,'120120','2026-02-02','2026','SMV',NULL,0,'2026-04-21 09:06:18'),(11,13,1760.00,'5050','2026-02-02','2026','SMV','kevin 50',0,'2026-04-22 00:41:01'),(12,14,40000.00,'5555','2026-02-03','2026','SMV',NULL,0,'2026-04-22 00:41:56'),(13,15,1000.00,'4594849','2025-12-02','2026','Leonardo',NULL,0,'2026-04-22 06:46:50'),(14,15,1000.00,'4594849','2025-12-02','2024, 2025, 2026','Leonardo',NULL,0,'2026-04-22 06:50:14'),(15,16,324.40,'0.0','0000-00-00',NULL,'',NULL,0,'2026-04-22 06:58:17'),(16,17,1288.60,'0.0','0000-00-00',NULL,'',NULL,0,'2026-04-22 06:58:18'),(17,18,3213.00,'0.0','0000-00-00',NULL,'',NULL,0,'2026-04-22 06:58:18'),(18,19,2208.00,'0.0','0000-00-00',NULL,'',NULL,0,'2026-04-22 06:58:18'),(19,20,2161.80,'0.0','0000-00-00',NULL,'',NULL,0,'2026-04-22 06:58:18'),(20,21,558.00,'0.0','0000-00-00',NULL,'',NULL,0,'2026-04-22 06:58:18'),(21,22,4355.40,'0.0','0000-00-00',NULL,'',NULL,0,'2026-04-22 06:58:18'),(22,23,927.00,'0.0','0000-00-00',NULL,'',NULL,0,'2026-04-22 06:58:18'),(23,24,557.80,'0.0','0000-00-00',NULL,'',NULL,0,'2026-04-22 06:58:18'),(24,25,9793.60,'0.0','0000-00-00',NULL,'',NULL,0,'2026-04-22 06:58:18'),(25,26,2920.20,'0.0','0000-00-00',NULL,'',NULL,0,'2026-04-22 06:58:19'),(26,27,2920.20,'0.0','0000-00-00',NULL,'',NULL,0,'2026-04-22 06:58:19'),(27,28,2920.20,'0.0','0000-00-00',NULL,'',NULL,0,'2026-04-22 06:58:19'),(28,29,2920.20,'0.0','0000-00-00',NULL,'',NULL,0,'2026-04-22 06:58:19'),(29,30,2920.20,'0.0','0000-00-00',NULL,'',NULL,0,'2026-04-22 06:58:19'),(30,31,2920.00,'0.0','0000-00-00',NULL,'',NULL,0,'2026-04-22 06:58:19'),(31,32,2920.20,'0.0','0000-00-00',NULL,'',NULL,0,'2026-04-22 06:58:19'),(32,33,3304.60,'0.0','0000-00-00',NULL,'',NULL,0,'2026-04-22 06:58:19'),(33,34,3406.80,'0.0','0000-00-00',NULL,'',NULL,0,'2026-04-22 06:58:19'),(34,35,3406.60,'0.0','0000-00-00',NULL,'',NULL,0,'2026-04-22 06:58:20'),(35,36,4957.00,'0.0','0000-00-00',NULL,'',NULL,0,'2026-04-22 06:58:20'),(36,37,4957.00,'0.0','0000-00-00',NULL,'',NULL,0,'2026-04-22 06:58:20'),(37,38,1194.60,'0.0','0000-00-00',NULL,'',NULL,0,'2026-04-22 06:58:20'),(38,39,9023.40,'0.0','0000-00-00',NULL,'',NULL,0,'2026-04-22 06:58:20'),(39,40,1800.00,'0.0','0000-00-00',NULL,'',NULL,0,'2026-04-22 06:58:20'),(40,41,360.00,'0.0','0000-00-00',NULL,'',NULL,0,'2026-04-22 06:58:20'),(41,42,288.00,'0.0','0000-00-00',NULL,'',NULL,0,'2026-04-22 06:58:20'),(42,43,2295.40,'0.0','0000-00-00',NULL,'',NULL,0,'2026-04-22 06:58:20'),(43,44,2112.00,'0.0','0000-00-00',NULL,'',NULL,0,'2026-04-22 06:58:20'),(44,45,1700.00,'5050','2026-02-02','2026','SMV',NULL,0,'2026-04-22 07:01:10'),(45,14,40000.00,'5555','2026-02-03','2024, 2025, 2026','SMV',NULL,0,'2026-04-22 07:02:06'),(46,46,3500.00,'500.0','0000-00-00','2026-04-01','',NULL,0,'2026-04-22 07:12:39'),(47,47,1960.00,'0.0','0000-00-00','2026-04-02','',NULL,0,'2026-04-22 07:12:40'),(48,48,2100.00,'500.0','0000-00-00','2026-02-02','',NULL,0,'2026-04-22 07:14:11'),(49,49,2100.00,'500.0','0000-00-00','2026-02-02','',NULL,0,'2026-04-22 07:27:45'),(50,10,1760.00,'120120','2026-02-02','2024, 2025','SMV','None',0,'2026-04-22 08:06:12'),(51,49,2100.00,'2203','2026-02-02','2024, 2025, 2026','SMV','None',0,'2026-04-22 09:31:42'),(52,53,10100.00,'02520','2020-02-02','2020','SMV','Kevin',0,'2026-04-27 07:30:00'),(53,54,1700.00,'02520','2022-02-02','2022','SMV','jojo',0,'2026-04-27 07:32:30'),(54,55,1616.00,'02820','2026-02-02','2026','SMV','Jojo',0,'2026-04-27 07:50:53');
/*!40000 ALTER TABLE `payments` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `properties`
--

DROP TABLE IF EXISTS `properties`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `properties` (
  `id` int(11) NOT NULL AUTO_INCREMENT,
  `td_number` varchar(255) NOT NULL,
  `owner_name` varchar(255) NOT NULL,
  `payor_name` varchar(255) DEFAULT NULL,
  `lot_number` varchar(255) DEFAULT NULL,
  `area` varchar(255) DEFAULT NULL,
  `location` varchar(255) DEFAULT NULL,
  `kind_of_property` varchar(100) DEFAULT NULL,
  `accountable_officer` varchar(255) DEFAULT NULL,
  `assessed_value` decimal(12,2) DEFAULT 0.00,
  `penalty` decimal(12,2) DEFAULT 0.00,
  `or_number` varchar(255) DEFAULT NULL,
  `or_date` date DEFAULT NULL,
  `tax_year` varchar(50) DEFAULT NULL,
  `is_deleted` tinyint(1) NOT NULL DEFAULT 0,
  `created_at` timestamp NOT NULL DEFAULT current_timestamp(),
  PRIMARY KEY (`id`),
  KEY `idx_properties_is_deleted` (`is_deleted`),
  KEY `idx_properties_td_number` (`td_number`),
  KEY `idx_properties_owner_name` (`owner_name`(100)),
  KEY `idx_properties_accountable_officer` (`accountable_officer`(100)),
  KEY `idx_properties_is_deleted_td_number` (`is_deleted`,`td_number`)
) ENGINE=InnoDB AUTO_INCREMENT=56 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `properties`
--

LOCK TABLES `properties` WRITE;
/*!40000 ALTER TABLE `properties` DISABLE KEYS */;
INSERT INTO `properties` VALUES (9,'06-0001-0001','kevin','kevin 67','1','1','West','None','JSJS',800000.00,160.00,'8080','2026-02-08','2026',0,'2026-04-21 08:22:58'),(10,'06-0001-0001','kevin','None','1','1','West','Residential','SMV',80000.00,600.00,'120120','2026-02-02','2024, 2025',0,'2026-04-21 09:05:34'),(11,'06-0001-0001','kevin',NULL,'1','1','West','Residential','SMV',80000.00,160.00,'120120','2026-02-02','2026',1,'2026-04-21 09:06:17'),(13,'06-0001-0005','Kevin Macalinao','kevin 50','1','1','North','Residential','SMV',80000.00,160.00,'5050','2026-02-02','2026',0,'2026-04-22 00:41:01'),(14,'06-0001-0002','Kevin Macalinao',NULL,'1','1','West','Agriculture','SMV',4000000.00,1000.00,'5555','2026-02-03','2024, 2025, 2026',0,'2026-04-22 00:41:56'),(15,'06-0017-00112','Dela torre, Reymundo',NULL,'3','1234','Lipit','Agricultural','Leonardo',90040.00,-360.16,'4594849','2025-12-02','2024, 2025, 2026',0,'2026-04-22 06:46:49'),(16,'06-0004-00800','RAMIL, ALFREDO L. MTO RAMIL, LEONARDA',NULL,'','','','','{\'id\': 3, \'username\': \'kevin\', \'role\': \'Admin\'}',16220.00,0.00,'',NULL,'',0,'2026-04-22 06:58:17'),(17,'06-0005-00676','CRISTE, HENRY MTO CALVO, ROSELLA',NULL,'','','','','{\'id\': 3, \'username\': \'kevin\', \'role\': \'Admin\'}',64430.00,0.00,'',NULL,'',0,'2026-04-22 06:58:18'),(18,'06-0008-00229','FERRERAS, BLANDINA',NULL,'','','','','{\'id\': 3, \'username\': \'kevin\', \'role\': \'Admin\'}',160650.00,0.00,'',NULL,'',0,'2026-04-22 06:58:18'),(19,'06-0009-00728','SANTIAGO, ARLINE (S)',NULL,'','','','','{\'id\': 3, \'username\': \'kevin\', \'role\': \'Admin\'}',110400.00,0.00,'',NULL,'',0,'2026-04-22 06:58:18'),(20,'06-0009-01120','FAJARDO, MARC D.',NULL,'','','','','{\'id\': 3, \'username\': \'kevin\', \'role\': \'Admin\'}',108090.00,0.00,'',NULL,'',0,'2026-04-22 06:58:18'),(21,'06-0009-01254','VALENZUELA, ROMAN MTO BERNARDINO, AMELIA',NULL,'','','','','{\'id\': 3, \'username\': \'kevin\', \'role\': \'Admin\'}',27900.00,0.00,'',NULL,'',0,'2026-04-22 06:58:18'),(22,'06-0009-01251','MATUSALEM, DEXTER A. & MATUSALEM, GINALYN E.',NULL,'','','','','{\'id\': 3, \'username\': \'kevin\', \'role\': \'Admin\'}',217770.00,0.00,'',NULL,'',0,'2026-04-22 06:58:18'),(23,'06-0012-00098','MOLINA, DAZZLE B. (S)',NULL,'','','','','{\'id\': 3, \'username\': \'kevin\', \'role\': \'Admin\'}',46350.00,0.00,'',NULL,'',0,'2026-04-22 06:58:18'),(24,'06-0012-01471','BELLEZA, WILLIAM P. (S)',NULL,'','','','','{\'id\': 3, \'username\': \'kevin\', \'role\': \'Admin\'}',27890.00,0.00,'',NULL,'',0,'2026-04-22 06:58:18'),(25,'06-0012-00950','BAYA, VIOLETA C/O OFARIL, WILFREDO',NULL,'','','','','{\'id\': 3, \'username\': \'kevin\', \'role\': \'Admin\'}',489680.00,0.00,'',NULL,'',0,'2026-04-22 06:58:18'),(26,'06-0015-00177','MIER, MA. AURORA',NULL,'','','','','{\'id\': 3, \'username\': \'kevin\', \'role\': \'Admin\'}',146010.00,0.00,'',NULL,'',0,'2026-04-22 06:58:19'),(27,'06-0015-00176','MIER, MA. AURORA',NULL,'','','','','{\'id\': 3, \'username\': \'kevin\', \'role\': \'Admin\'}',146010.00,0.00,'',NULL,'',0,'2026-04-22 06:58:19'),(28,'06-0015-00028','MIER, JOSE F. JR. MTO MIER, SUSAN ET. AL',NULL,'','','','','{\'id\': 3, \'username\': \'kevin\', \'role\': \'Admin\'}',146010.00,0.00,'',NULL,'',0,'2026-04-22 06:58:19'),(29,'06-0015-00174','MIER, MA. ELENA',NULL,'','','','','{\'id\': 3, \'username\': \'kevin\', \'role\': \'Admin\'}',146010.00,0.00,'',NULL,'',0,'2026-04-22 06:58:19'),(30,'06-0015-00173','MIER, FLORDELIZA',NULL,'','','','','{\'id\': 3, \'username\': \'kevin\', \'role\': \'Admin\'}',146010.00,0.00,'',NULL,'',0,'2026-04-22 06:58:19'),(31,'06-0015-00172','MIER, JOSE JR.',NULL,'','','','','{\'id\': 3, \'username\': \'kevin\', \'role\': \'Admin\'}',146000.00,0.00,'',NULL,'',0,'2026-04-22 06:58:19'),(32,'06-0015-00553','MIER, MARITA MTO VALDEHUESA, MANUEL JR.',NULL,'','','','','{\'id\': 3, \'username\': \'kevin\', \'role\': \'Admin\'}',146010.00,0.00,'',NULL,'',0,'2026-04-22 06:58:19'),(33,'06-0015-00170','MIER, MA. LUISA',NULL,'','','','','{\'id\': 3, \'username\': \'kevin\', \'role\': \'Admin\'}',165230.00,0.00,'',NULL,'',0,'2026-04-22 06:58:19'),(34,'06-0015-00171','MIER, MA. AURORA',NULL,'','','','','{\'id\': 3, \'username\': \'kevin\', \'role\': \'Admin\'}',170340.00,0.00,'',NULL,'',0,'2026-04-22 06:58:19'),(35,'06-0015-00552','VALDEHUESA, MARITA MIER MTO VALDEHUESA, MANUEL',NULL,'','','','','{\'id\': 3, \'username\': \'kevin\', \'role\': \'Admin\'}',170330.00,0.00,'',NULL,'',0,'2026-04-22 06:58:20'),(36,'06-0015-00554','MIER, MA. ELENA',NULL,'','','','','{\'id\': 3, \'username\': \'kevin\', \'role\': \'Admin\'}',247850.00,0.00,'',NULL,'',0,'2026-04-22 06:58:20'),(37,'06-0015-00559','MIER, FLORDELIZA (S)',NULL,'','','','','{\'id\': 3, \'username\': \'kevin\', \'role\': \'Admin\'}',247850.00,0.00,'',NULL,'',0,'2026-04-22 06:58:20'),(38,'06-0015-00322','LIBED, ERLINDA',NULL,'','','','','{\'id\': 3, \'username\': \'kevin\', \'role\': \'Admin\'}',59730.00,0.00,'',NULL,'',0,'2026-04-22 06:58:20'),(39,'06-0015-00200','DUASO, MARCOS',NULL,'','','','','{\'id\': 3, \'username\': \'kevin\', \'role\': \'Admin\'}',451170.00,0.00,'',NULL,'',0,'2026-04-22 06:58:20'),(40,'06-0015-00011','SPS. SANTOS, ANTHONY & SANTOS, ANGELITA T.',NULL,'','','','','{\'id\': 3, \'username\': \'kevin\', \'role\': \'Admin\'}',90000.00,0.00,'',NULL,'',0,'2026-04-22 06:58:20'),(41,'06-0017-00691','AURE, ROSARIO C. (W)',NULL,'','','','','{\'id\': 3, \'username\': \'kevin\', \'role\': \'Admin\'}',18000.00,0.00,'',NULL,'',0,'2026-04-22 06:58:20'),(42,'06-0017-00690','AURE, ROSARIO C. (W)',NULL,'','','','','{\'id\': 3, \'username\': \'kevin\', \'role\': \'Admin\'}',14400.00,0.00,'',NULL,'',0,'2026-04-22 06:58:20'),(43,'06-0019-00343','LAURELES, HAROLD AMATORIO (M)',NULL,'','','','','{\'id\': 3, \'username\': \'kevin\', \'role\': \'Admin\'}',114770.00,0.00,'',NULL,'',0,'2026-04-22 06:58:20'),(44,'06-0001-00171','ROMERO, AMBROCIO',NULL,'','','','','{\'id\': 3, \'username\': \'kevin\', \'role\': \'Admin\'}',105600.00,0.00,'',NULL,'',0,'2026-04-22 06:58:20'),(45,'06-0001-0002','Kevin',NULL,'1','1','West','Agricultural','SMV',80000.00,100.00,'5050','2026-02-02','2026',0,'2026-04-22 07:01:10'),(46,'TD-2026-001','Juan Dela Cruz',NULL,'Lot-12','120 sqm','Poblacion','','Maria Santos',150000.00,500.00,'OR-1001','2026-04-01','2026.0',0,'2026-04-22 07:12:39'),(47,'TD-2026-002','Ana Reyes',NULL,'Lot-19','95 sqm','Barangay East','','Maria Santos',98000.00,0.00,'OR-1002','2026-04-02','2026.0',0,'2026-04-22 07:12:40'),(48,'06-0001-0009','Kevin',NULL,'1','1','West','','SMV',80000.00,500.00,'2202','2026-02-02','2026.0',1,'2026-04-22 07:14:11'),(49,'06-0001-0008','Kevin','None','1.0','1.0','West','','SMV',80000.00,500.00,'2203','2026-02-02','2024, 2025, 2026',0,'2026-04-22 07:27:45'),(53,'06-0001-0006','Joseph','Kevin','1','1','West','Residential','SMV',500000.00,100.00,'02520','2020-02-02','2020',0,'2026-04-27 07:30:00'),(54,'06-0001-0002','Kevin','jojo','1','1','West','Residential','SMV',80000.00,100.00,'02520','2022-02-02','2022',0,'2026-04-27 07:32:30'),(55,'06-0001-0005','Kevin','Jojo','1','1','South','Agri','SMV',80000.00,16.00,'02820','2026-02-02','2026',0,'2026-04-27 07:50:53');
/*!40000 ALTER TABLE `properties` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `property_billings`
--

DROP TABLE IF EXISTS `property_billings`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `property_billings` (
  `id` int(11) NOT NULL AUTO_INCREMENT,
  `property_id` int(11) NOT NULL,
  `tax_year` varchar(20) NOT NULL,
  `assessed_value` decimal(12,2) NOT NULL DEFAULT 0.00,
  `penalty` decimal(12,2) NOT NULL DEFAULT 0.00,
  `amount_paid` decimal(12,2) NOT NULL DEFAULT 0.00,
  `is_archived` tinyint(1) NOT NULL DEFAULT 0,
  `created_at` timestamp NOT NULL DEFAULT current_timestamp(),
  `updated_at` timestamp NOT NULL DEFAULT current_timestamp() ON UPDATE current_timestamp(),
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_property_billings_property_year` (`property_id`,`tax_year`),
  KEY `idx_property_billings_tax_year` (`tax_year`),
  KEY `idx_property_billings_is_archived` (`is_archived`),
  CONSTRAINT `fk_property_billings_property` FOREIGN KEY (`property_id`) REFERENCES `properties` (`id`) ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE=InnoDB AUTO_INCREMENT=112 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `property_billings`
--

LOCK TABLES `property_billings` WRITE;
/*!40000 ALTER TABLE `property_billings` DISABLE KEYS */;
INSERT INTO `property_billings` VALUES (8,9,'2026',800000.00,160.00,16160.00,0,'2026-04-21 08:22:58','2026-04-22 08:17:24'),(9,10,'2026',80000.00,160.00,1760.00,0,'2026-04-21 09:05:34','2026-04-21 09:49:05'),(10,11,'2026',80000.00,160.00,1760.00,0,'2026-04-21 09:06:17','2026-04-21 09:49:05'),(12,13,'2026',80000.00,160.00,1760.00,0,'2026-04-22 00:41:01','2026-04-22 07:52:16'),(13,14,'2026',4000000.00,1000.00,40000.00,0,'2026-04-22 00:41:56','2026-04-22 07:02:06'),(14,15,'2026',90040.00,-360.16,1000.00,0,'2026-04-22 06:46:49','2026-04-22 06:50:14'),(15,15,'2024',90040.00,-360.16,1000.00,0,'2026-04-22 06:50:14','2026-04-22 06:50:14'),(16,15,'2025',90040.00,-360.16,0.00,0,'2026-04-22 06:50:14','2026-04-22 06:50:14'),(18,16,'None',16220.00,0.00,0.00,0,'2026-04-22 06:58:17','2026-04-22 07:50:57'),(24,17,'None',64430.00,0.00,0.00,0,'2026-04-22 06:58:18','2026-04-22 07:50:57'),(25,18,'None',160650.00,0.00,0.00,0,'2026-04-22 06:58:18','2026-04-22 07:50:57'),(26,19,'None',110400.00,0.00,0.00,0,'2026-04-22 06:58:18','2026-04-22 07:50:57'),(27,20,'None',108090.00,0.00,0.00,0,'2026-04-22 06:58:18','2026-04-22 07:50:57'),(30,21,'None',27900.00,0.00,0.00,0,'2026-04-22 06:58:18','2026-04-22 07:50:57'),(31,22,'None',217770.00,0.00,0.00,0,'2026-04-22 06:58:18','2026-04-22 07:50:57'),(32,23,'None',46350.00,0.00,0.00,0,'2026-04-22 06:58:18','2026-04-22 07:50:57'),(33,24,'None',27890.00,0.00,0.00,0,'2026-04-22 06:58:18','2026-04-22 07:50:57'),(34,25,'None',489680.00,0.00,0.00,0,'2026-04-22 06:58:18','2026-04-22 07:50:57'),(44,26,'None',146010.00,0.00,0.00,0,'2026-04-22 06:58:19','2026-04-22 07:50:57'),(45,27,'None',146010.00,0.00,0.00,0,'2026-04-22 06:58:19','2026-04-22 07:50:57'),(46,28,'None',146010.00,0.00,0.00,0,'2026-04-22 06:58:19','2026-04-22 07:50:57'),(47,29,'None',146010.00,0.00,0.00,0,'2026-04-22 06:58:19','2026-04-22 07:50:57'),(48,30,'None',146010.00,0.00,0.00,0,'2026-04-22 06:58:19','2026-04-22 07:50:57'),(49,31,'None',146000.00,0.00,0.00,0,'2026-04-22 06:58:19','2026-04-22 07:50:57'),(50,32,'None',146010.00,0.00,0.00,0,'2026-04-22 06:58:19','2026-04-22 07:50:57'),(51,33,'None',165230.00,0.00,0.00,0,'2026-04-22 06:58:19','2026-04-22 07:50:57'),(52,34,'None',170340.00,0.00,0.00,0,'2026-04-22 06:58:19','2026-04-22 07:50:57'),(53,35,'None',170330.00,0.00,0.00,0,'2026-04-22 06:58:20','2026-04-22 07:50:57'),(54,36,'None',247850.00,0.00,0.00,0,'2026-04-22 06:58:20','2026-04-22 07:50:57'),(55,37,'None',247850.00,0.00,0.00,0,'2026-04-22 06:58:20','2026-04-22 07:50:57'),(56,38,'None',59730.00,0.00,0.00,0,'2026-04-22 06:58:20','2026-04-22 07:50:57'),(57,39,'None',451170.00,0.00,0.00,0,'2026-04-22 06:58:20','2026-04-22 07:50:57'),(58,40,'None',90000.00,0.00,0.00,0,'2026-04-22 06:58:20','2026-04-22 07:50:57'),(60,41,'None',18000.00,0.00,0.00,0,'2026-04-22 06:58:20','2026-04-22 07:50:57'),(61,42,'None',14400.00,0.00,0.00,0,'2026-04-22 06:58:20','2026-04-22 07:50:57'),(66,43,'None',114770.00,0.00,0.00,0,'2026-04-22 06:58:20','2026-04-22 07:50:57'),(67,44,'None',105600.00,0.00,0.00,0,'2026-04-22 06:58:20','2026-04-22 07:50:57'),(78,45,'2026',80000.00,100.00,1700.00,0,'2026-04-22 07:01:10','2026-04-22 07:01:10'),(79,14,'2024',4000000.00,1000.00,40000.00,0,'2026-04-22 07:02:06','2026-04-22 07:02:06'),(80,14,'2025',4000000.00,1000.00,0.00,0,'2026-04-22 07:02:06','2026-04-22 07:02:06'),(82,46,'2026-04-01',150000.00,500.00,0.00,0,'2026-04-22 07:12:39','2026-04-22 07:50:57'),(83,47,'2026-04-02',98000.00,0.00,0.00,0,'2026-04-22 07:12:40','2026-04-22 07:50:57'),(90,48,'2026-02-02',80000.00,500.00,0.00,0,'2026-04-22 07:14:11','2026-04-22 07:50:57'),(97,49,'2026',26666.67,166.67,2800.00,0,'2026-04-22 07:27:45','2026-04-22 09:31:42'),(101,10,'2024',40000.00,300.00,1100.00,0,'2026-04-22 08:06:12','2026-04-28 03:36:26'),(102,10,'2025',40000.00,300.00,660.00,0,'2026-04-22 08:06:12','2026-04-28 03:36:26'),(104,49,'2024',26666.66,166.66,699.99,0,'2026-04-22 09:31:42','2026-04-22 09:31:42'),(105,49,'2025',26666.67,166.67,700.00,0,'2026-04-22 09:31:42','2026-04-22 09:31:42'),(107,53,'2020',500000.00,100.00,10100.00,0,'2026-04-27 07:30:00','2026-04-27 07:30:00'),(108,54,'2022',80000.00,100.00,1700.00,0,'2026-04-27 07:32:30','2026-04-27 07:32:30'),(109,55,'2026',80000.00,16.00,1616.00,0,'2026-04-27 07:50:53','2026-04-27 07:50:53');
/*!40000 ALTER TABLE `property_billings` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `property_edit_locks`
--

DROP TABLE IF EXISTS `property_edit_locks`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `property_edit_locks` (
  `property_id` int(11) NOT NULL,
  `locked_by` varchar(255) NOT NULL,
  `locked_at` datetime NOT NULL,
  PRIMARY KEY (`property_id`),
  KEY `idx_property_edit_locks_locked_at` (`locked_at`),
  CONSTRAINT `fk_property_edit_locks_property` FOREIGN KEY (`property_id`) REFERENCES `properties` (`id`) ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `property_edit_locks`
--

LOCK TABLES `property_edit_locks` WRITE;
/*!40000 ALTER TABLE `property_edit_locks` DISABLE KEYS */;
/*!40000 ALTER TABLE `property_edit_locks` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `receipt_history`
--

DROP TABLE IF EXISTS `receipt_history`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `receipt_history` (
  `id` int(11) NOT NULL AUTO_INCREMENT,
  `property_id` int(11) NOT NULL,
  `payment_id` int(11) DEFAULT NULL,
  `td_number` varchar(255) DEFAULT NULL,
  `owner_name` varchar(255) DEFAULT NULL,
  `payor_name` varchar(255) DEFAULT NULL,
  `or_number` varchar(255) DEFAULT NULL,
  `tax_year` varchar(20) DEFAULT NULL,
  `amount` decimal(12,2) NOT NULL DEFAULT 0.00,
  `file_path` text NOT NULL,
  `generated_by` varchar(255) DEFAULT NULL,
  `generated_at` datetime NOT NULL,
  PRIMARY KEY (`id`),
  KEY `idx_receipt_history_property_id` (`property_id`),
  KEY `idx_receipt_history_or_number` (`or_number`),
  KEY `idx_receipt_history_generated_at` (`generated_at`),
  CONSTRAINT `fk_receipt_history_property` FOREIGN KEY (`property_id`) REFERENCES `properties` (`id`) ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE=InnoDB AUTO_INCREMENT=7 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `receipt_history`
--

LOCK TABLES `receipt_history` WRITE;
/*!40000 ALTER TABLE `receipt_history` DISABLE KEYS */;
INSERT INTO `receipt_history` VALUES (1,9,8,'06-0001-0001','kevin',NULL,'8080','2026',16160.00,'C:\\Users\\user\\Desktop\\MTO\\receipts\\OR_8080_06-0001-0001_20260421_164732.pdf','{\'id\': 3, \'username\': \'Kevin\', \'role\': \'Admin\'}','2026-04-21 16:47:32'),(2,14,12,'06-0001-0002','Kevin Macalinao',NULL,'5555','2026',40000.00,'C:\\Users\\user\\Desktop\\MTO\\receipts\\OR_5555_06-0001-0002_20260422_084307.pdf','{\'id\': 3, \'username\': \'kevin\', \'role\': \'Admin\'}','2026-04-22 08:43:07'),(3,11,10,'06-0001-0001','kevin',NULL,'120120','2026',1760.00,'C:\\Users\\user\\Desktop\\MTO\\receipts\\OR_1201201_06-0001-0001_20260420_111856.pdf','{\'id\': 4, \'username\': \'leo\', \'role\': \'Encoder\'}','2026-04-22 10:47:17'),(4,15,13,'06-0017-00112','Dela torre, Reymundo',NULL,'4594849','2026',1000.00,'C:\\Users\\user\\Desktop\\MTO\\receipts\\OR_4594849_06-0017-00112_20260422_144742.pdf','{\'id\': 3, \'username\': \'kevin\', \'role\': \'Admin\'}','2026-04-22 14:47:38'),(5,14,45,'06-0001-0002','Kevin Macalinao',NULL,'5555','2024, 2025, 2026',40000.00,'C:\\Users\\user\\Desktop\\MTO\\receipts\\OR_5555_06-0001-0002_20260422_084307.pdf','{\'id\': 3, \'username\': \'kevin\', \'role\': \'Admin\'}','2026-04-22 15:31:18'),(6,13,11,'06-0001-0005','Kevin Macalinao','kevin','5050','2026',1760.00,'C:\\Users\\user\\Desktop\\MTO\\receipts\\OR_5050_06-0001-0005_20260422_155230.pdf','{\'id\': 3, \'username\': \'kevin\', \'role\': \'Admin\'}','2026-04-22 15:52:30');
/*!40000 ALTER TABLE `receipt_history` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `user_edit_locks`
--

DROP TABLE IF EXISTS `user_edit_locks`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `user_edit_locks` (
  `user_id` int(11) NOT NULL,
  `locked_by` varchar(255) NOT NULL,
  `locked_at` datetime NOT NULL,
  PRIMARY KEY (`user_id`),
  KEY `idx_user_edit_locks_locked_at` (`locked_at`),
  CONSTRAINT `fk_user_edit_locks_user` FOREIGN KEY (`user_id`) REFERENCES `users` (`id`) ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `user_edit_locks`
--

LOCK TABLES `user_edit_locks` WRITE;
/*!40000 ALTER TABLE `user_edit_locks` DISABLE KEYS */;
/*!40000 ALTER TABLE `user_edit_locks` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `users`
--

DROP TABLE IF EXISTS `users`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `users` (
  `id` int(11) NOT NULL AUTO_INCREMENT,
  `full_name` varchar(255) NOT NULL DEFAULT '',
  `username` varchar(50) NOT NULL,
  `password` varchar(255) NOT NULL,
  `role` varchar(20) NOT NULL,
  `is_deleted` tinyint(1) NOT NULL DEFAULT 0,
  `last_login` datetime DEFAULT NULL,
  `created_at` timestamp NOT NULL DEFAULT current_timestamp(),
  PRIMARY KEY (`id`)
) ENGINE=InnoDB AUTO_INCREMENT=6 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `users`
--

LOCK TABLES `users` WRITE;
/*!40000 ALTER TABLE `users` DISABLE KEYS */;
INSERT INTO `users` VALUES (3,'Kevin Joseph Macalinao','kevin','pbkdf2_sha256$200000$FQAs//etjQzr66zsnOh1Wg==$veahOvv5lkSe5Sy5taCF18lvS+sGP/XeHYdNx+Dbai4=','Admin',0,NULL,'2026-04-21 07:45:31'),(4,'Leonardo Marzan Jr.','leo','pbkdf2_sha256$200000$aERHQstmIxEF/ZES6cSd0Q==$QV0/BgujG5Uiv9iLlN/N0iPdV8AtYcCiRRiMvo3KrLU=','Encoder',0,NULL,'2026-04-21 08:25:50'),(5,'Raquel Somera','raquel','pbkdf2_sha256$200000$Le7vDSxi+4M0xCPKZGmBhw==$K9LiXfv/4+JA6t8O4naO7QUhK9+Ka2d9CPgZXEqa7Ok=','Viewer',0,NULL,'2026-04-22 06:36:36');
/*!40000 ALTER TABLE `users` ENABLE KEYS */;
UNLOCK TABLES;
/*!40103 SET TIME_ZONE=@OLD_TIME_ZONE */;

/*!40101 SET SQL_MODE=@OLD_SQL_MODE */;
/*!40014 SET FOREIGN_KEY_CHECKS=@OLD_FOREIGN_KEY_CHECKS */;
/*!40014 SET UNIQUE_CHECKS=@OLD_UNIQUE_CHECKS */;
/*!40101 SET CHARACTER_SET_CLIENT=@OLD_CHARACTER_SET_CLIENT */;
/*!40101 SET CHARACTER_SET_RESULTS=@OLD_CHARACTER_SET_RESULTS */;
/*!40101 SET COLLATION_CONNECTION=@OLD_COLLATION_CONNECTION */;
/*!40111 SET SQL_NOTES=@OLD_SQL_NOTES */;

-- Dump completed on 2026-04-28 13:28:17
