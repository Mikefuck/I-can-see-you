param(
    [string]$JdkPath = '',
    [string]$SdkPath = '',
    [string]$TestTempPath = '',
    [switch]$SkipTests,
    [switch]$VerifyServer
)
$ErrorActionPreference = 'Stop'
$androidProject = $PSScriptRoot
$repositoryRoot = Split-Path -Parent $androidProject
$androidRuntime = Join-Path $repositoryRoot '.runtime\android'
New-Item -ItemType Directory -Path $androidRuntime -Force | Out-Null
if (!$JdkPath) {
    if ($env:JAVA_HOME -and (Test-Path -LiteralPath "$env:JAVA_HOME\bin\java.exe")) { $JdkPath = $env:JAVA_HOME }
    else { $JdkPath = (Get-ChildItem -LiteralPath 'C:\Program Files\Java' -Directory -Filter 'jdk-*' | Sort-Object Name -Descending | Select-Object -First 1).FullName }
}
if (!$SdkPath) { $SdkPath = Join-Path $androidRuntime 'sdk' }
if (!(Test-Path -LiteralPath (Join-Path $JdkPath 'bin\java.exe'))) { throw '请安装 JDK 21，并用 -JdkPath 指定目录（Android 16 启动测试需要 JDK 21）。' }
if (!(Test-Path -LiteralPath (Join-Path $SdkPath 'platforms\android-36\android.jar'))) { throw '请安装 Android SDK Platform 36 和 Build Tools 36.0.0，并用 -SdkPath 指定 SDK。' }
$env:JAVA_HOME = $JdkPath
$env:GRADLE_USER_HOME = Join-Path $androidRuntime 'gradle-home'
$env:ANDROID_USER_HOME = Join-Path $androidRuntime 'android-user'
Remove-Item Env:ANDROID_SDK_HOME -ErrorAction SilentlyContinue
$env:ANDROID_SDK_ROOT = $SdkPath
function ConvertTo-JavaProperty([string]$text) {
    $escaped = New-Object Text.StringBuilder
    foreach ($character in $text.ToCharArray()) {
        $code = [int]$character
        if ($code -gt 127) { [void]$escaped.Append(('\u{0:x4}' -f $code)) }
        elseif ($character -eq '\' -or $character -eq ':' -or $character -eq '=') { [void]$escaped.Append('\').Append($character) }
        else { [void]$escaped.Append($character) }
    }
    return $escaped.ToString()
}
$sdkPropertyPath = $SdkPath.Replace('\','/')
if ($SdkPath.StartsWith($repositoryRoot + '\', [StringComparison]::OrdinalIgnoreCase)) {
    $sdkPropertyPath = '../' + $SdkPath.Substring($repositoryRoot.Length + 1).Replace('\','/')
}
$sdkProperty = ConvertTo-JavaProperty $sdkPropertyPath
Set-Content -LiteralPath (Join-Path $androidProject 'local.properties') -Value "sdk.dir=$sdkProperty" -Encoding ascii
$signingHome = Join-Path $androidRuntime 'signing'
$signingFile = Join-Path $androidRuntime 'signing.properties'
$keyFile = Join-Path $signingHome 'focusledger.jks'
if (!(Test-Path -LiteralPath $signingFile)) {
    if (Test-Path -LiteralPath $keyFile) { throw '签名密钥已存在但签名配置缺失。请恢复原 signing.properties，避免无法覆盖升级。' }
    New-Item -ItemType Directory -Path $signingHome -Force | Out-Null
    $randomBytes = New-Object byte[] 24
    $randomGenerator = [Security.Cryptography.RandomNumberGenerator]::Create()
    $randomGenerator.GetBytes($randomBytes); $randomGenerator.Dispose()
    $signingPassword = ([BitConverter]::ToString($randomBytes)).Replace('-','').ToLowerInvariant()
    $env:FOCUSLEDGER_SIGNING_PASSWORD = $signingPassword
    & (Join-Path $JdkPath 'bin\keytool.exe') -genkeypair -keystore $keyFile -alias focusledger -keyalg RSA -keysize 3072 -validity 10000 -dname 'CN=FocusLedger Local Android Release' -storepass:env FOCUSLEDGER_SIGNING_PASSWORD -keypass:env FOCUSLEDGER_SIGNING_PASSWORD -storetype JKS *> (Join-Path $androidRuntime 'signing-keygen.log')
    if ($LASTEXITCODE -ne 0) { throw '生成本地签名密钥失败，请查看 .runtime/android/signing-keygen.log。' }
    $keyProperty = ConvertTo-JavaProperty ($keyFile.Replace('\','/'))
    @("storeFile=$keyProperty", "storePassword=$signingPassword", 'keyAlias=focusledger', "keyPassword=$signingPassword") | Set-Content -LiteralPath $signingFile -Encoding ascii
    Remove-Item Env:FOCUSLEDGER_SIGNING_PASSWORD
    $signingPassword = $null
}
$gradleExe = Join-Path $androidRuntime 'gradle-8.13\bin\gradle.bat'
if (!(Test-Path -LiteralPath $gradleExe)) { $gradleExe = Join-Path $androidProject 'gradlew.bat' }
$gradleTasks = @(':app:assembleRelease', ':app:lintRelease')
if (!$SkipTests) { $gradleTasks += ':app:exportDebugTestClasspath' }
& $gradleExe -p $androidProject @gradleTasks --console plain
if ($LASTEXITCODE -ne 0) { throw 'Android 构建或静态检查失败。' }
if (!$SkipTests) {
    # Direct JUnit avoids Gradle 8.13's Windows non-ASCII worker argument-file issue.
    $classpath = [IO.File]::ReadAllText((Join-Path $androidProject 'app\build\testDebugUnitTest-classpath.txt'), [Text.Encoding]::UTF8).Trim()
    $testHome = Join-Path $androidRuntime 'test-home'
    # Robolectric's Windows native libraries cannot load ICU data from a non-ASCII path.
    $testTemp = if ($TestTempPath) { $TestTempPath } else { Join-Path ([IO.Path]::GetTempPath()) 'FocusLedger-android-tests' }
    New-Item -ItemType Directory -Path $testHome -Force | Out-Null
    New-Item -ItemType Directory -Path $testTemp -Force | Out-Null
    Push-Location (Join-Path $androidProject 'app')
    try {
        & (Join-Path $JdkPath 'bin\java.exe') '-Dfile.encoding=UTF-8' "-Duser.home=$testHome" "-Djava.io.tmpdir=$testTemp" '-Drobolectric.dependency.repo.url=https://repo.maven.apache.org/maven2' -cp $classpath org.junit.runner.JUnitCore com.focusledger.android.UsageReducerTest com.focusledger.android.ConfigTest com.focusledger.android.TransportTest com.focusledger.android.StartupTest com.focusledger.android.NavigationTest com.focusledger.android.LedgerStoreTest com.focusledger.android.MusicReaderTest com.focusledger.android.UploaderTest com.focusledger.android.PowerBehaviorTest
        if ($LASTEXITCODE -ne 0) { throw 'Android 逻辑、网络或界面启动测试失败。' }
    } finally { Pop-Location }
    if ($VerifyServer) {
        $testPython = Join-Path $repositoryRoot '.runtime\build-venv\Scripts\python.exe'
        if (!(Test-Path -LiteralPath $testPython)) { throw '请先在 .runtime/build-venv 安装 requirements-dev.txt，以运行真实服务端联调。' }
        & $testPython (Join-Path $androidProject 'tools\verify_server.py') --java (Join-Path $JdkPath 'bin\java.exe') --classpath $classpath
        if ($LASTEXITCODE -ne 0) { throw 'Android 与真实服务端联调失败。' }
    }
}
$releaseHome = Join-Path $androidProject 'release'
New-Item -ItemType Directory -Path $releaseHome -Force | Out-Null
$releaseApk = Join-Path $releaseHome 'FocusLedger-android.apk'
Copy-Item -LiteralPath (Join-Path $androidProject 'app\build\outputs\apk\release\app-release.apk') -Destination $releaseApk -Force
& (Join-Path $SdkPath 'build-tools\36.0.0\apksigner.bat') verify --verbose $releaseApk
if ($LASTEXITCODE -ne 0) { throw 'APK 签名校验失败。' }
$releaseHash = (Get-FileHash -LiteralPath $releaseApk -Algorithm SHA256).Hash.ToLowerInvariant()
Set-Content -LiteralPath (Join-Path $releaseHome 'SHA256SUMS.txt') -Value "$releaseHash  FocusLedger-android.apk" -Encoding ascii
Write-Output "APK: $releaseApk"
Write-Output '请备份 .runtime/android/signing 和 signing.properties；后续覆盖升级必须使用同一签名。'
