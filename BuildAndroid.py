import os
import subprocess
import configparser
import shutil
import html.parser
import pathlib
import urllib 
import urllib.request
import ssl
import re
import zipfile
import stat
import sys

TEMPLATES = {}

TEMPLATES["settings.gradle"] = """include ':app'

"""
TEMPLATES["build.gradle"] = """
// Top-level build file where you can add configuration options common to all sub-projects/modules.
buildscript {
    repositories {
       google()
       jcenter()
    }
    dependencies {
        classpath 'com.android.tools.build:gradle:3.5.2'
    }
}

allprojects {
    repositories {
        google()
        jcenter()
    }
}

task clean(type: Delete) {
    delete rootProject.buildDir
}
"""

TEMPLATES["app/build.gradle"] = """
apply plugin: 'com.android.application'

android {
    compileSdkVersion 29

    defaultConfig {
        applicationId = '$$$Android.AppPackageName$$$'
        minSdkVersion 14
        targetSdkVersion 28
        externalNativeBuild {
            cmake {
                arguments '-DANDROID_STL=c++_static' 
            }
        }
    }
    buildTypes {
        release {
            minifyEnabled false
            proguardFiles getDefaultProguardFile('proguard-android.txt'),
                    'proguard-rules.pro'
        }
    }
    externalNativeBuild {
        cmake {
            version '3.17.0'
            path 'src/main/cpp/CMakeLists.txt'
        }
    }
}
"""
"""
dependencies {
    implementation fileTree(dir: 'libs', include: ['*.jar'])
    implementation 'androidx.appcompat:appcompat:1.0.2'
    implementation 'androidx.constraintlayout:constraintlayout:1.1.3'
}
"""

TEMPLATES["app/src/main/AndroidManifest.xml"] = """
<!-- BEGIN_INCLUDE(manifest) -->
<manifest xmlns:android="http://schemas.android.com/apk/res/android"
          package="$$$Android.AppPackageName$$$"
          android:versionCode="$$$Build.Iteration$$$"
          android:versionName="$$$Build.Version$$$">

  <!-- This .apk has no Java code itself, so set hasCode to false. -->
  <application
      android:allowBackup="false"
      android:fullBackupContent="false"
      android:icon="@mipmap/ic_launcher"
      android:label="@string/app_name"
      android:hasCode="false">

    <!-- Our activity is the built-in NativeActivity framework class.
         This will take care of integrating with our NDK code. -->
    <activity android:name="android.app.NativeActivity"
              android:label="@string/app_name"
              android:configChanges="orientation|keyboardHidden">
      <!-- Tell NativeActivity the name of our .so -->
      <meta-data android:name="android.app.lib_name"
                 android:value="native_$$$Application.BinaryName$$$" />
      <intent-filter>
        <action android:name="android.intent.action.MAIN" />
        <category android:name="android.intent.category.LAUNCHER" />
      </intent-filter>
    </activity>
  </application>
</manifest>
<!-- END_INCLUDE(manifest) -->
"""


TEMPLATES["app/src/main/cpp/CMakeLists.txt"] = """
cmake_minimum_required(VERSION 3.4.1)
project($$$Application.BinaryName$$$)
add_subdirectory(/home/ankurv/avid/cmake avid)

# build native_app_glue as a static lib
set(${CMAKE_C_FLAGS}, "${CMAKE_C_FLAGS}")

set(CMAKE_CXX_FLAGS "${CMAKE_CXX_FLAGS} -std=gnu++11 -Wall -Werror")

# Export ANativeActivity_onCreate(),
# Refer to: https://github.com/android-ndk/ndk/issues/381.
set(CMAKE_SHARED_LINKER_FLAGS "${CMAKE_SHARED_LINKER_FLAGS} -u ANativeActivity_onCreate")

add_library(native_$$$Application.BinaryName$$$ SHARED ${ANDROID_NDK}/sources/android/native_app_glue/android_native_app_glue.c)

target_include_directories(native_$$$Application.BinaryName$$$ PRIVATE ${ANDROID_NDK}/sources/android/native_app_glue)

# add lib dependencies
#find_library(applib $$$Application.BinaryName$$$ HINTS ${CMAKE_CURRENT_LIST_DIR}/../../../../  ${CMAKE_CURRENT_LIST_DIR}../../../  ${CMAKE_CURRENT_LIST_DIR}../../../../../)
set(applib $$$Application.BinaryName$$$)
if (NOT TARGET ${applib})
    message(FATAL_ERROR "Cannot find Target ${applib}"e)
endif()
target_link_libraries(native_$$$Application.BinaryName$$$ ${applib} android EGL GLESv2 GLESv1_CM log)

"""

TEMPLATES["app/src/main/res/values/strings.xml"] = """<?xml version="1.0" encoding="utf-8"?>
<resources>
    <string name="app_name">$$$Application.Name$$$</string>
</resources>
"""

IMAGES = {}
IMAGES["app/src/main/res/mipmap-hdpi/ic_launcher.png"]      = {"img" : "Icon", "width": 72, "height": 72}
IMAGES["app/src/main/res/mipmap-mdpi/ic_launcher.png"]      = {"img" : "Icon", "width": 48, "height": 48}
IMAGES["app/src/main/res/mipmap-xhdpi/ic_launcher.png"]     = {"img" : "Icon", "width": 96, "height": 96}
IMAGES["app/src/main/res/mipmap-xxhdpi/ic_launcher.png"]    = {"img" : "Icon", "width": 144, "height": 144}

class HTMLUrlExtractor(html.parser.HTMLParser):
    def __init__(self, url):
        text = urllib.request.urlopen(url, timeout=10, context=ssl._create_unverified_context()).read().decode("utf-8")
        self.baseurl = url
        self.urls = {}
        self.href = None
        self.text = None
        super(HTMLUrlExtractor, self).__init__()
        self.feed(text)

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            self.text = ""
            self.href = next((urllib.parse.urljoin(self.baseurl, attr[1]) for attr in attrs if attr[0] == "href"), None)

    def handle_endtag(self, tag):
        if self.href is not None:
            # print(self.href, self.text)
            self.urls[self.href] = self.text
        self.href = None
        self.text = None

    def handle_data(self, data):
        if self.href is not None:
            self.text = data

class BuildEnv:
    def __init__ (self):
        self._config = configparser.ConfigParser()
        self._configfilename = os.path.join(os.path.dirname(os.path.realpath(__file__)), ".config")
        if (os.path.exists(self._configfilename)): 
            self._config.read(self._configfilename)

    def _ConfigValue(self, name):
        val = self._config
        for p in name.split("."):
            if not p in val: return None
            val = val[p]
        return val

    def _WriteValue(self, name, value):
        names = name.split(".")
        c = self._config
        if (len(names) > 1): 
            for d in names[0:-1]:
                if d not in c: c[d] = {}
                c = c[d]
        c[names[-1]] = str(value)
        with open(self._configfilename, 'w') as fd: self._config.write(fd)
        return value

    def _DetectValue(self, name, envvars):
        if envvars: 
            for e in envvars: 
                p = os.path.exists(os.path.expandvars(e))
                if p: return p
        return self._WriteValue(name, input("Cannot Detect Path for : " + name + " :: "))

    def _SearchExeInPath(self, bindir, name):
        path = next(pathlib.Path(bindir).rglob(name), None)
        print(bindir, path, name)
        if sys.platform == "win32" or sys.platform == "Windows":
            path = path or next(pathlib.Path(bindir).rglob(name + ".exe"), None) or next(pathlib.Path(bindir).rglob(name + ".bat"), None)
        if path: os.chmod(path, os.stat(path).st_mode | stat.S_IEXEC)
        return str(path) if path else None

    def _Download(self, downloadpath, name, url, pattern):
        if pattern != None:
            url = [u for u in HTMLUrlExtractor(url).urls if re.search(pattern, u)][0]
        downloadtofile = os.path.join(downloadpath,"tmp", name + ".zip")
        print("Downloading {} at {} ::  Url = {}".format(name, downloadpath, url))
        os.makedirs(os.path.dirname(downloadtofile), exist_ok=True)
        bindir = os.path.join(downloadpath, name)
        if not os.path.exists(bindir):
            if not os.path.exists(downloadtofile):
                urllib.request.urlretrieve(url, downloadtofile)
            zip_ref = zipfile.ZipFile(downloadtofile, 'r')
            extractdir = os.path.join(downloadpath, name)
            zip_ref.extractall(extractdir)
            zip_ref.close()
            os.remove(downloadtofile)
        return self._SearchExeInPath(bindir, name)

    def _FindOrGetConfig(self, name, envvars):
        return self._ConfigValue(name) or self._DetectValue(name, envvars)

    def _FindOrDownload(self, name, config, envvars, url, pattern):
        p = shutil.which(name)
        if p: return p
        p = self._ConfigValue(config)
        if p: p = self._SearchExeInPath(p, name)
        if p: return p
        path = self._FindOrGetConfig("BuildEnv.BinDownloadPath", ["BUILD_TOOLS_DOWNLOAD_PATH"])
        return self._WriteValue(config, self._Download(path, name, url, pattern))

    def GetJava(self):
        LinkDir = 'http://jdk.java.net/14/'
        Pattern = 'openjdk-14_windows-x64_bin.zip'
        return self._FindOrDownload('java', config = "Android.JavaPath", envvars = ['${JAVA_HOME}/bin'], url = LinkDir, pattern = Pattern)

    def GetAndroidSdkRoot(self):
        LinkDir = 'https://developer.android.com/studio'
        Pattern = 'commandlinetools-win-6200805_latest.zip'
        return self._FindOrDownload('sdkmanager', config = "Android.SdkManagerPath", envvars = ['${ANDROID_SDK_ROOT}/tools/bin'], url = LinkDir, pattern = Pattern)
        #return self._FindOrGetConfig("Android.SdkRoot", ['${ANDROID_SDK_ROOT}', '${ANDROID_HOME}'])
    
    def GetAndroidStudioPath(self):
        return self._FindOrGetConfig("Android.StudioPath", ['${ANDROID_HOME}'])

    def GetImageMagick(self):
        LinkDir = 'https://imagemagick.org/download/binaries/'
        Pattern = '\\bImageMagick-7.*-portable-Q16-x64.zip\\b'
        return os.path.dirname(self._FindOrDownload('magick', config = "ImageMagick.Path", envvars = None, url = LinkDir, pattern = Pattern))

    def GetGradlePath(self):
        LinkDir = "https://services.gradle.org/distributions/"
        Pattern = 'gradle-5.4.1-bin.zip'
        return self._FindOrDownload('gradle', config = "Android.GradlePath", envvars = None, url = LinkDir, pattern = Pattern)

    def GetBuildPath(self):
        return self._FindOrGetConfig("BuildEnv.BuildPath", ['${BUILD_PATH}'])

    def GetCMakePath(self):
        LinkDir = { "Windows" : 'https://github.com/Kitware/CMake/releases' }.get(sys.platform, None)
        Pattern = { "Windows" : 'cmake-3\.??\..*-win64-x64.zip' }.get(sys.platform, None)
        return self._FindOrDownload('cmake', config = "BuildEnv.CMakePath", envvars = None, url = LinkDir, pattern = Pattern)

    def GetDownloadPath(self):
        return self._FindOrGetConfig("BuildEnv.BinDownloadPath")

class AndroidApk:
    def __init__(self, config):
        self.buildenv = BuildEnv()
        self.config = configparser.ConfigParser()
        self.config.read(str(config))
        self.gradle = self.buildenv.GetGradlePath()
        self.imagemagick_convert = os.path.join(self.buildenv.GetImageMagick(), 'convert')
        self.builddir = self.buildenv.GetBuildPath()
        self.sdkroot = self.buildenv.GetAndroidSdkRoot()
        self.java = self.buildenv.GetJava()
        self.cmake = self.buildenv.GetCMakePath()
#        self.studiopath = self.buildenv.GetAndroidStudioPath()

    def Generate(self):
        self._Run([self.gradle, "wrapper"])
        for k, v in TEMPLATES.items():
            self._GenerateFileWithContents(k, self._ExpandTemplate(v))
        for k, v in IMAGES.items():
            self._GenerateImage(k, v)

    def _Run(self, cmd, env = None):
        my_env = os.environ
        if env != None:
            for k, v in env.items():
                my_env[k] = v
        rslt = subprocess.run(cmd, cwd=self.builddir, capture_output=True, env = my_env)
        if rslt.returncode != 0:
            raise Exception("Error Building : Command = " + " ".join(cmd) + "\n\n STDOUT = " + rslt.stdout.decode() + "\n\nSTDERR = " + rslt.stderr.decode())

    def Build(self):
        self._Run(
            ["./gradlew", "build"], 
            {
                "ANDROID_HOME" : self.sdkroot,
                "ANDROID_SDK_ROOT" : self.sdkroot,
                "JAVA_HOME" :  os.path.join(self.studiopath, "jre")
            })       

    def _GenerateFileWithContents(self, path, newcontents):
        fname =  os.path.join(self.builddir, path)
        os.makedirs(os.path.dirname(fname), exist_ok=True)
        contents = open(fname, 'r').read() if os.path.exists(fname) else None
        if contents == newcontents: return
        open(fname, 'w').write(newcontents)
    
    def _GenerateImage(self, path, imginfo):
        if os.path.exists(path): return
        srcsvg = os.path.join(os.path.dirname(self.configfile), self.config["Images"][imginfo["img"]])
        if not os.path.exists(srcsvg): raise Exception("Cannot find Image Source: ", srcsvg)
        fname =  os.path.join(self.builddir, path)
        os.makedirs(os.path.dirname(fname), exist_ok=True)

        extent =  str(imginfo["width"]) + "x" +  str(imginfo["height"])
        if "scalex" in imginfo.keys() and "scaley" in imginfo.keys():
            scale = str(imginfo["scalex"]) + "x" + str(imginfo["scaley"])
        else:
            scale = extent
        self._Run([
            self.imagemagick_convert,
            "-density", scale,
            "-extent", extent ,
            "-gravity", "center",
            "-background", "none",
            srcsvg,
            fname,
        ])

    def _ConfigValue(self, name):
        val = self.config
        for p in name.split("."):
            val = val[p]
        return val

    def _ExpandTemplate(self, tmpl):
        startmarker = '$$$'
        endmarker = '$$$'
        retval = tmpl
        offset= retval.find(startmarker, 0)
        while(offset != -1):
            s = offset + len(startmarker)
            e = retval.find(endmarker, s)
            val = self._ConfigValue(retval[s:e])
            retval = retval[0:offset] + val + retval[e + len(endmarker):]
            offset = retval.find(startmarker, offset)
        return retval

builder = AndroidApk("appmanifest.config")
builder.Generate()
builder.Build()